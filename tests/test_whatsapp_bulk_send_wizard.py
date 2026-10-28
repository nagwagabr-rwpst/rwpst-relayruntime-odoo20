# -*- coding: utf-8 -*-

import base64
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

# 1x1 transparent PNG
_TINY_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)


@tagged('post_install', '-at_install', 'relayruntime')
class TestWhatsAppBulkSendWizardAction(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['whatsapp.config'].search([('active', '=', True)], limit=1)
        if not cls.config:
            cls.config = cls.env['whatsapp.config'].create({
                'name': 'Test WhatsApp Config',
                'provider_type': 'mock_provider',
                'active': True,
                'daily_send_limit': 10000,
            })
        cls.partner = cls.env['res.partner'].create({
            'name': 'Wizard Action Test Partner',
            'phone': '+201987654321',
        })
        cls.attachments = cls.env['ir.attachment'].create([
            {
                'name': 'wizard-test-a.pdf',
                'type': 'binary',
                'raw': b'%PDF-1.4 a',
                'mimetype': 'application/pdf',
            },
            {
                'name': 'wizard-test-b.pdf',
                'type': 'binary',
                'raw': b'%PDF-1.4 b',
                'mimetype': 'application/pdf',
            },
        ])

    def _assert_valid_notification_action(self, action):
        self.assertIsInstance(action, dict)
        self.assertEqual(action.get('type'), 'ir.actions.client')
        self.assertEqual(action.get('tag'), 'display_notification')
        params = action.get('params')
        self.assertIsInstance(params, dict)
        self.assertIn('title', params)
        self.assertIn('message', params)
        self.assertIn(params.get('type'), ('success', 'warning', 'info', 'danger'))
        self.assertIs(params.get('sticky'), False)

        next_action = params.get('next')
        self.assertIsInstance(next_action, dict)
        self.assertEqual(next_action.get('type'), 'ir.actions.act_window_close')
        # Odoo 19 _preprocessAction requires views on act_window; bare view_mode crashes.
        self.assertNotIn('view_mode', next_action)

    @patch('odoo.addons.relayruntime.services.whatsapp_bulk_service.WhatsAppBulkSender.send_to_partners')
    def test_action_send_returns_valid_action_with_multiple_attachments(self, mock_send):
        mock_send.return_value = {
            'total': 1,
            'sent': 1,
            'failed': 0,
            'skipped': 0,
            'cooldown_count': 0,
            'total_attachments_sent': 2,
        }
        self.assertEqual(
            [attachment.raw.content for attachment in self.attachments],
            [b'%PDF-1.4 a', b'%PDF-1.4 b'],
        )
        self.assertTrue(all(attachment.file_size for attachment in self.attachments))
        wizard = self.env['whatsapp.bulk.send.wizard'].create({
            'recipient_ids': [(6, 0, self.partner.ids)],
            'message': 'Bulk wizard action test',
            'attachment_ids': [(6, 0, self.attachments.ids)],
        })
        with patch.object(self.env.cr, 'commit'):
            action = wizard.action_send()

        self._assert_valid_notification_action(action)
        self.assertEqual(wizard.state, 'done')
        self.assertEqual(wizard.sent_count, 1)
        self.assertEqual(wizard.total_attachments_sent, 2)
        self.assertIn('Bulk send finished', action['params']['message'])

    def test_finished_notification_helper_never_returns_malformed_next(self):
        wizard = self.env['whatsapp.bulk.send.wizard'].create({
            'recipient_ids': [(6, 0, self.partner.ids)],
        })
        action = wizard._action_send_finished_notification({
            'total': 2,
            'sent': 2,
            'failed': 0,
            'skipped': 0,
            'cooldown_count': 0,
            'total_attachments_sent': 3,
        })
        self._assert_valid_notification_action(action)
