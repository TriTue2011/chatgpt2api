"""The bot must pass the same valid requests as a direct MCP caller."""
from unittest.mock import patch, PropertyMock

import pytest

from services import mcp_client as mc
from services.search_service import SearchService, _intent_router, _extract_city


def search_with(server, query, handler):
    with patch.object(_intent_router, 'detect', return_value={
        'mcp_tools': [server], 'kb_collections': [], 'needs_live': True,
    }), patch.object(SearchService, 'search_combo', new_callable=PropertyMock, return_value=['test']), \
            patch.object(SearchService, '_get_backend', return_value=None), \
            patch.object(mc, 'call_mcp_tool', side_effect=handler):
        return SearchService().search_all(query)


def test_weather_tools_are_available_to_model():
    tools = [{'type': 'function', 'function': {'name': name}} for name in
             ['get_current_weather', 'get_forecast', 'get_weather_alerts', 'search_web']]
    with patch.object(mc, 'get_enabled_mcp_tools', return_value=tools), \
            patch.object(mc, 'is_device_query', return_value=False), \
            patch.object(mc, 'is_server_admin_query', return_value=False):
        names = {t['function']['name'] for t in mc.get_relevant_mcp_tools('Thời tiết Hà Nội hôm nay')}
    assert 'get_current_weather' in names
    assert 'get_forecast' in names


@pytest.mark.parametrize('query,city', [
    ('Thời tiết Hà Nội hôm nay', 'Hà Nội'),
    ('Dự báo thời tiết Vũng Tàu ngày mai', 'Vũng Tàu'),
    ('thời tiết ở Hoàng Mai, Hà Nội lúc này', 'Hoàng Mai, Hà Nội'),
])
def test_geocoder_receives_location_without_time_or_weather_prefix(query, city):
    assert _extract_city(query) == city


def test_news_search_receives_keyword_not_query():
    def call(tool, args, **kw):
        assert tool == 'search_news'
        assert args['keyword'] == 'kinh tế'
        assert 'query' not in args
        return 'Tin tức kinh tế mới lấy từ nguồn tin chính thức.'
    assert search_with('vn_news', 'Tin tức kinh tế hôm nay', call)


def test_general_news_fetches_latest_instead_of_searching_boilerplate():
    def call(tool, args, **kw):
        assert tool == 'get_news'
        assert set(args) == {'limit'}
        return 'Các tin mới nhất lấy từ những nguồn đã cấu hình.'
    assert search_with('vn_news', 'Tin tức hôm nay', call)


def test_stock_receives_explicit_symbol_without_search_arguments():
    def call(tool, args, **kw):
        assert tool == 'get_stock_price'
        assert args == {'symbol': 'FPT'}
        return 'FPT: dữ liệu giá và thời điểm do nguồn cung cấp.'
    assert search_with('vn_stock', 'Giá cổ phiếu FPT hôm nay', call)


@pytest.mark.parametrize('query', ['Tình hình chứng khoán', 'Giá cổ phiếu hôm nay', 'cổ phiếu nào tốt'])
def test_stock_without_symbol_does_not_guess_or_send_invalid_request(query):
    with patch.object(mc, 'call_mcp_tool') as call:
        search_with('vn_stock', query, call)
    call.assert_not_called()


def test_domain_mcp_is_not_cut_off_at_generic_search_deadline():
    import concurrent.futures
    original = concurrent.futures.as_completed
    def completed(fs, timeout=None):
        assert timeout >= 20, 'live stock call took 8.2s; the old 8s limit discarded it'
        return original(fs, timeout=timeout)
    with patch.object(concurrent.futures, 'as_completed', side_effect=completed):
        assert search_with('vn_stock', 'cổ phiếu FPT', lambda *a, **k: 'Bảng giá cổ phiếu vừa lấy từ MCP.')


def test_transport_exception_is_logged_without_secondary_logger_error():
    from services.search_service import logger
    with patch.object(logger, 'warning', wraps=logger.warning) as warning:
        assert search_with('vn_news', 'Tin tức hôm nay', lambda *a, **k: (_ for _ in ()).throw(TimeoutError())) == []
    assert any(isinstance(c.args[0], dict) and c.args[0].get('event') == 'search_mcp_failed'
               for c in warning.call_args_list)


@pytest.mark.parametrize('payload', [
    {'content': [{'type': 'text', 'text': '1 validation error: missing symbol'}]},
    {'structuredContent': {'error': 'upstream unavailable'}},
    {'content': []},
])
def test_mcp_tool_error_flag_survives_text_conversion(payload):
    session = mc.MCPSession('http://localhost/mcp')
    result = session._ket_qua_tool('test_tool', {}, {'result': {**payload, 'isError': True}})
    assert mc.la_loi_mcp(result)
    assert 'test_tool' in result


def test_successful_tool_text_is_preserved():
    session = mc.MCPSession('http://localhost/mcp')
    assert session._ket_qua_tool('test_tool', {}, {'result': {
        'isError': False, 'content': [{'type': 'text', 'text': 'valid data'}],
    }}) == 'valid data'
