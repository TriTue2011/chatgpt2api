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


def test_custom_search_does_not_choose_fast_image_model():
    from services.search_service import CustomProviderSearch
    from services.providers import custom_openai
    with patch.object(custom_openai, 'get_custom_providers', return_value={'agnes': {'prefix': 'agnes'}}), \
            patch.object(custom_openai, 'CustomOpenAIProvider') as provider:
        provider.return_value.list_models.return_value = [
            {'id': 'agnes/agnes-image-2.5-flash'}, {'id': 'agnes/chat-pro'},
        ]
        provider.return_value.chat_completions.return_value = {}
        CustomProviderSearch('agnes').search('Tin tức')
        assert provider.return_value.chat_completions.call_args.kwargs['model'] == 'chat-pro'


def test_authoritative_data_survives_faster_web_results_and_output_cap():
    with patch.object(_intent_router, 'detect', return_value={
        'mcp_tools': ['vn_stock'], 'kb_collections': [], 'needs_live': True,
    }), patch.object(SearchService, 'search_combo', new_callable=PropertyMock, return_value=['test']), \
            patch.object(SearchService, 'max_results', new_callable=PropertyMock, return_value=1), \
            patch.object(SearchService, '_get_backend') as backend, \
            patch.object(mc, 'call_mcp_tool', return_value='FPT: bảng giá chính thức vừa lấy.'), \
            patch('concurrent.futures.as_completed', side_effect=lambda fs, timeout: iter(sorted(fs, key=lambda f: fs[f][0] == 'mcp'))):
        backend.return_value.search.return_value = [{'title': f'web {i}', 'url': f'https://example.com/{i}'} for i in range(15)]
        rows = SearchService().search_all('Giá cổ phiếu FPT')
    assert rows[0]['title'] == '[vn_stock]'
    assert len(rows) == 4


@pytest.fixture
def custom_server():
    server = {'id': 'acme', 'name': 'Acme integration', 'url': 'https://acme.example/mcp', 'enabled': True}
    tool = {'type': 'function', 'function': {'name': 'create_workflow', 'parameters': {}}}
    route = mc._session_key(*mc._connection_options(server))
    with patch.object(mc, '_configured_servers', return_value=[server]), \
            patch.object(mc, 'get_enabled_mcp_tools', return_value=[tool]), \
            patch.dict(mc._tool_routes, {'create_workflow': (route, 'create_workflow')}, clear=True):
        yield server, tool


@pytest.mark.parametrize('query', ['Tạo workflow Acme', 'Tích hợp dữ liệu', 'Giá vàng qua Acme'])
def test_user_added_mcp_survives_builtin_keyword_filter(custom_server, query):
    with patch.object(mc, 'is_device_query', return_value=False), \
            patch.object(mc, 'is_server_admin_query', return_value=False):
        assert mc.get_relevant_mcp_tools(query) == [custom_server[1]]


def test_disabled_external_server_does_not_expose_tools(custom_server):
    custom_server[0]['enabled'] = False
    with patch.object(mc, 'is_device_query', return_value=False), \
            patch.object(mc, 'is_server_admin_query', return_value=False):
        assert mc.get_relevant_mcp_tools('Tạo workflow Acme') == []


def test_explicit_external_mcp_is_not_replaced_by_builtin_prefetch(custom_server):
    with patch.object(mc, 'call_mcp_tool') as call:
        assert mc.prefetch_realtime_context('Giá vàng qua Acme') is None
        assert mc.prefetch_kb_context('Tra cứu điện nước qua Acme') is None
    call.assert_not_called()


def test_external_integration_command_is_not_filtered_as_smart_home(custom_server):
    import services.protocol.openai_v1_chat_complete as gateway
    with patch.object(mc, 'is_device_query', return_value=False), \
            patch.object(mc, 'is_server_admin_query', return_value=False), \
            patch.object(gateway, '_is_smarthome_query', return_value=True), \
            patch.object(gateway, '_is_trivial_chat', return_value=False):
        tools = gateway._inject_mcp_tools(None, user_text='Tạo workflow Acme', no_smart_home=True)
    assert custom_server[1] in tools
