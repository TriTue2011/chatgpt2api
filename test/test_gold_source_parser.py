"""Keep BTMC gold rows, units and date distinct from the adjacent silver table."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('currency_parser_test', Path(__file__).resolve().parents[1] / 'vn-mcp-hub/src/vn/currency.py')
module = importlib.util.module_from_spec(spec)
class MCP:
    def __init__(self, *a): pass
    def tool(self): return lambda fn: fn
with patch.dict(sys.modules, {'fastmcp': types.SimpleNamespace(FastMCP=MCP)}):
    spec.loader.exec_module(module)

HTML = '''<div><table class="bd_price_home"><tr><th>Loại vàng</th></tr>
<tr><td rowspan="2"><img></td><td>VÀNG MIẾNG SJC</td><td>999.9 (24k)</td><td>10000</td><td>11000</td></tr>
<tr><td>NHẪN TRÒN TRƠN</td><td>999.9 (24k)</td><td>10100</td><td>11100</td></tr>
<tr><td>ĐỒNG XU 0.1</td><td>999.9 (24k)</td><td>1010</td><td>1110</td></tr>
<tr><td>VÀNG NGUYÊN LIỆU</td><td>24k</td><td>9000</td><td>Liên hệ</td></tr>
</table></div><span>Cập nhật lúc 07/09/2026 16:11</span><div>ĐVT 1 = 1.000 VNĐ</div>
<table class="bd_price_home"><tr><th>Tên sản phẩm bạc</th></tr><tr><td>BẠC</td><td>10</td><td>20</td></tr></table>
Cập nhật lúc 07/09/2026 20:02'''

class GoldTests(unittest.TestCase):
    def test_gold_rowspan_and_units_do_not_mix_with_silver(self):
        rows = module._parse_btmc(HTML)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[1]['buy'], '10100')
        self.assertEqual(rows[2]['buy'], '1010')
        self.assertEqual(rows[3]['sell'], 'Liên hệ')
        self.assertTrue(all(r['updated_at'] == '07/09/2026 16:11' for r in rows))
        self.assertTrue(all('VNĐ' in r['unit'] and 'lượng' not in r['unit'] for r in rows))

    def test_missing_unit_date_or_price_is_not_data(self):
        for html in ('<html>blocked</html>', HTML.replace('ĐVT 1 = 1.000 VNĐ', ''), HTML.replace('Cập nhật lúc 07/09/2026 16:11', '')):
            self.assertEqual(module._parse_btmc(html), [])

    def test_partial_source_outage_preserves_verified_btmc_without_fake_pnj_quote(self):
        with patch.object(module, '_fetch_sjc', return_value=[]), patch.object(module, '_fetch_doji', return_value=[]), patch.object(module, '_fetch_btmc', return_value=module._parse_btmc(HTML)):
            result = module.get_gold_prices()
        self.assertIn('https://btmc.vn/', result)
        self.assertIn('07/09/2026 16:11', result)
        self.assertNotIn('hôm nay', result)
        self.assertNotIn('PNJ', result)
        self.assertIn('Chưa lấy được bảng trực tiếp từ: SJC, DOJI', result)
        self.assertIn('chưa có nguồn trực tiếp', module.get_gold_prices('pnj'))
