# -*- coding: utf-8 -*-

import base64
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.binary import BinaryBytes

from odoo.addons.relayruntime.services.providers.mock_provider import MockProvider
from odoo.addons.relayruntime.services.whatsapp_bulk_service import WhatsAppBulkSender
from odoo.addons.relayruntime.services.whatsapp_product_service import WhatsAppProductService
from odoo.addons.relayruntime.services.whatsapp_safety_utils import WhatsAppSafetyValidator
from odoo.addons.relayruntime.services.whatsapp_service import WhatsAppService

# 1x1 transparent PNG
_TINY_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)
_PDF_BYTES = b'%PDF-1.4 test'


@tagged('post_install', '-at_install', 'relayruntime')
class TestWhatsAppBulkProduct(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_service = WhatsAppProductService(cls.env)
        cls.config = cls.env['whatsapp.config'].search([('active', '=', True)], limit=1)
        if not cls.config:
            cls.config = cls.env['whatsapp.config'].create({
                'name': 'Test WhatsApp Config',
                'provider_type': 'mock_provider',
                'active': True,
                'simulate_success_rate': 100.0,
                'simulate_failure_rate': 0.0,
                'simulate_timeout_rate': 0.0,
                'simulate_rate_limit_rate': 0.0,
                'simulate_attachment_failure_rate': 0.0,
                'simulated_latency_ms': 0.0,
                'min_delay_seconds': 0.0,
                'max_delay_seconds': 0.0,
                'daily_send_limit': 10000,
            })
        else:
            cls.config.write({
                'provider_type': 'mock_provider',
                'simulate_success_rate': 100.0,
                'simulate_failure_rate': 0.0,
                'simulate_timeout_rate': 0.0,
                'simulate_rate_limit_rate': 0.0,
                'simulate_attachment_failure_rate': 0.0,
                'simulated_latency_ms': 0.0,
                'min_delay_seconds': 0.0,
                'max_delay_seconds': 0.0,
            })

        cls.partner = cls.env['res.partner'].create({
            'name': 'WhatsApp Bulk Test Partner',
            'phone': '+201234567890',
        })
        cls.product = cls.env['product.template'].create({
            'name': 'Bulk Test Product',
            'list_price': 99.0,
            'description_sale': 'Sale description for bulk test.',
            'image_1920': BinaryBytes(_TINY_PNG),
        })
        cls.free_attachment = cls.env['ir.attachment'].create({
            'name': 'bulk-test.pdf',
            'type': 'binary',
            'raw': _PDF_BYTES,
            'mimetype': 'application/pdf',
        })

    def test_prepare_send_plan_accepts_include_product_description(self):
        plan = self.product_service.prepare_send_plan(
            self.product,
            use_product_images=True,
            include_product_description=True,
        )
        self.assertIn('Sale description for bulk test.', plan['message'])
        self.assertEqual(len(plan['product_image_steps']), 1)

    def test_prepare_send_plan_legacy_include_description_kwarg(self):
        plan = self.product_service.prepare_send_plan(
            self.product,
            use_product_images=False,
            include_description=True,
        )
        self.assertIn('Sale description for bulk test.', plan['message'])

    def test_prepare_send_plan_ignores_unknown_kwargs(self):
        plan = self.product_service.prepare_send_plan(
            self.product,
            use_product_images=False,
            include_product_description=True,
            future_option=True,
        )
        self.assertIn('Sale description for bulk test.', plan['message'])

    @patch('time.sleep', return_value=None)
    def test_bulk_send_with_free_attachments_products_and_descriptions(self, _sleep):
        campaign = self.env['whatsapp.bulk.campaign'].create({
            'name': 'Regression bulk product send',
            'message': '',
            'partner_ids': [(6, 0, self.partner.ids)],
            'product_ids': [(6, 0, self.product.ids)],
            'attachment_ids': [(6, 0, self.free_attachment.ids)],
            'use_product_images': True,
            'include_product_description': True,
        })
        self.assertEqual(self.free_attachment.file_size, len(_PDF_BYTES))
        self.assertEqual(
            WhatsAppSafetyValidator._attachment_size_bytes(self.free_attachment),
            len(_PDF_BYTES),
        )
        self.assertEqual(
            WhatsAppService.get_attachment_bytes(self.free_attachment),
            _PDF_BYTES,
        )
        sender = WhatsAppBulkSender(self.env, self.config, campaign)
        captured_media = []
        original_send_media = MockProvider.send_media_message

        def _capture_media(provider, recipient_number, message, media):
            captured_media.append(bytes(media.content or b''))
            return original_send_media(provider, recipient_number, message, media)

        with patch.object(sender, '_commit_progress'), \
                patch.object(MockProvider, 'send_media_message', _capture_media):
            stats = sender.send_to_partners(
                self.partner,
                '',
                free_attachments=self.free_attachment,
                products=self.product,
                use_product_images=True,
                include_product_description=True,
            )
        self.assertEqual(stats['total'], 1)
        self.assertEqual(stats['sent'], 1)
        self.assertEqual(stats['failed'], 0)
        self.assertGreater(stats['total_attachments_sent'], 0)
        self.assertEqual(len(captured_media), stats['total_attachments_sent'])
        self.assertTrue(all(captured_media))
        self.assertIn(_PDF_BYTES, captured_media)
        self.assertIn('Sale description for bulk test.', sender._catalog_message)
        self.assertEqual(len(sender._product_steps), 1)
