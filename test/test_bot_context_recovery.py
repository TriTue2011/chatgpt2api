"""Regressions from the personal Zalo conversation on 07/09/2026."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import channel_contacts as cc, mcp_client
from services.agent import capabilities as caps, reminders as rem, orchestrator as orch, ask_choices

REC = {'platform': 'zalop', 'bot_id': 'account-1', 'chat_id': '6643404425553198601',
       'kind': 'user', 'alias': 'Đại ca', 'chat_name': 'Đại ca', 'bot_label': 'Cá nhân'}
UID = 'zalop_' + REC['chat_id']
DIRECTORY = {'bot_id': REC['bot_id'], 'thread_id': REC['chat_id'], 'name': 'Đại ca',
             'kind': 'user', 'bot_label': 'Cá nhân', 'sources': ['admin']}


class ContextTests(unittest.TestCase):
    def test_configured_alias_and_observed_name_resolve_to_same_contact(self):
        observed = {**REC, 'alias': '', 'chat_name': '', 'display_name': 'Nguyễn Việt'}
        with patch.object(cc, 'list_contacts', return_value=[observed]), patch.object(cc, 'list_directory', return_value=[DIRECTORY]):
            for name in ('Đại ca', 'Nguyễn Việt', REC['chat_id']):
                hits = cc.resolve_alias(name, platform='zalop')
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]['alias'], 'Đại ca')

    def test_contacts_explicit_personal_overrides_wrong_model_channel(self):
        with patch.object(cc, 'resolve_alias', return_value=[REC]) as resolve:
            result = caps._h_contacts({'op': 'resolve', 'ref': 'Đại ca', 'platform': 'zalo'},
                                     {'user_id': UID, 'user_message': 'zalo cá nhân cho đại ca'})
        resolve.assert_called_once_with('Đại ca', platform='zalop', bot_id='')
        self.assertIn('Đại ca', result['text'])

    def test_contacts_list_defaults_to_ingress_directory(self):
        with patch.object(cc, 'directory_contacts', return_value=[REC]) as listing:
            caps._h_contacts({}, {'user_id': UID})
        listing.assert_called_once_with('zalop', '', q='')

    def test_ingress_account_survives_worker_boundary(self):
        with patch('services.zalo_personal.current_msg_ctx', return_value=('account-1', 1)), \
             patch.object(orch, '_orchestrate_locked', side_effect=lambda *a, **kw: rem._capture_delivery_ctx('zalop')):
            self.assertEqual(orch.orchestrate('xin chào', UID), {'account': 'account-1', 'thread_type': 1})
        self.assertIsNone(rem.delivery_context.get())

    def test_realtime_search_returns_actual_mcp_data_without_second_model(self):
        with patch.object(mcp_client, 'prefetch_realtime_context', return_value='Bảng BTMC: nguồn và thời điểm'), \
             patch.object(caps, 'call_model') as model:
            result = caps._h_web_search({'query': 'Giá vàng hôm nay'}, {'user_id': UID})
        model.assert_not_called()
        self.assertIn('BTMC', result['text'])

    def test_upstream_no_data_is_not_successful_mcp_evidence(self):
        self.assertTrue(mcp_client.la_loi_mcp('Không lấy được thông tin giá vàng lúc này.'))
        with patch.object(mcp_client, 'call_mcp_tool', return_value='Không lấy được thông tin giá vàng lúc này.'):
            self.assertIsNone(mcp_client.prefetch_realtime_context('Giá vàng hôm nay'))
        self.assertFalse(mcp_client.la_loi_mcp('Giá vàng BTMC\n| Vàng | 1 | 2 |\nChưa lấy được SJC.'))


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rem._reset_for_tests(Path(self.tmp.name) / 'reminders.sqlite')
        self.old_db = ask_choices._conn
        ask_choices._conn = sqlite3.connect(':memory:', check_same_thread=False)
        ask_choices._conn.execute('CREATE TABLE ask_pending(user_id TEXT PRIMARY KEY, choices TEXT, ts REAL)')
        ask_choices._reset_for_tests()
        self.args = {'mode': 'task', 'text': 'Lấy tin tức mới và thời tiết hôm nay, tổng hợp đầy đủ',
                     'every_day_at': '08:00', 'send_to': 'Đại ca', 'send_platform': 'zalop'}

    def tearDown(self):
        ask_choices._reset_for_tests()
        ask_choices._conn.close()
        ask_choices._conn = self.old_db
        rem._reset_for_tests()
        self.tmp.cleanup()

    def test_self_schedule_uses_current_chat_without_contact_question(self):
        with patch.object(caps, '_h_send_to_contact') as resolve:
            result = caps._h_schedule({**self.args, 'send_to': 'anh'}, {'user_id': UID})
        resolve.assert_not_called()
        rows = rem.list_for(UID)
        self.assertEqual(len(rows), 1, result)
        self.assertEqual(rows[0]['chat_id'], REC['chat_id'])

    def test_target_account_is_stored_separately_from_task(self):
        with patch.object(caps, '_h_send_to_contact', return_value={'resolved': [REC]}):
            caps._h_schedule(self.args, {'user_id': UID, 'user_message': 'đúng'})
        row = rem.list_for(UID)[0]
        self.assertEqual(row['text'], self.args['text'])
        self.assertEqual(json.loads(row['meta'])['delivery_targets'], [REC])

    def test_number_choice_survives_cache_reset_and_creates_once_without_model(self):
        with patch.object(caps, '_h_send_to_contact', return_value={'need_clarify': True, 'candidates': [REC]}):
            result = caps._h_schedule(self.args, {'user_id': UID})
        ask_choices.set_pending(UID, result['choices'])
        ask_choices._reset_for_tests()  # simulate process restart, SQLite still there
        with patch.object(orch, '_persist_history'), patch.object(orch.sess, 'load_history', return_value=[]), \
             patch.object(orch.run_journal, 'log_run'), patch.object(orch, 'call_model') as model:
            out = orch._orchestrate_locked('1', UID, ha_fastpath=False)
        model.assert_not_called()
        self.assertIn('đã đặt', out['text'])
        self.assertEqual(len(rem.list_for(UID)), 1)
        self.assertIsNone(ask_choices.get_pending(UID))

    def test_firing_task_sends_generated_body_once_to_saved_account(self):
        with patch.object(caps, '_h_send_to_contact', return_value={'resolved': [REC]}):
            caps._h_schedule(self.args, {'user_id': UID})
        row = rem.list_for(UID)[0]
        with patch.object(rem, '_run_task', return_value='Tin mới và dự báo đã lấy'), \
             patch.object(caps, '_send_one_contact', return_value=(True, 'ok')) as send, \
             patch.object(rem, '_send') as origin:
            rem._fire(row, row['next_run_at'])
        origin.assert_not_called()
        send.assert_called_once_with(REC, '⏰ Việc theo lịch:\nTin mới và dự báo đã lấy')

    def test_scheduled_runner_has_saved_delivery_context(self):
        def run(prompt, *a, **kw):
            self.assertIn('không gọi send_to_contact', prompt)
            self.assertEqual(rem._capture_delivery_ctx('zalop')['account'], 'account-1')
            return {'text': 'kết quả'}
        with patch.object(orch, 'orchestrate', side_effect=run), patch.object(rem, '_task_model', return_value=''):
            self.assertEqual(rem._run_task(UID, 'Tổng hợp tin', channel='zalop',
                             meta={'account': 'account-1', 'delivery_targets': [REC]}), 'kết quả')
