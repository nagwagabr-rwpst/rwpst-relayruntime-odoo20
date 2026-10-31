# -*- coding: utf-8 -*-

import logging

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WhatsAppProductService:
    """Build product catalog messages and image attachments for WhatsApp."""

    def __init__(self, env):
        self.env = env
        self.Attachment = env['ir.attachment']

    def build_catalog_message(self, products, include_description=False):
        """Return a formatted numbered product list message."""
        products = products.sorted(key=lambda p: p.display_name)
        if not products:
            return ''

        currency = self.env.company.currency_id
        symbol = currency.symbol or currency.name or ''
        lines = [_('New Products Available:'), '']
        for index, product in enumerate(products, start=1):
            price = product.list_price
            price_txt = '%s %s' % (price, symbol) if symbol else str(price)
            ref = (' [%s]' % product.default_code) if product.default_code else ''
            lines.append('%s. %s - %s%s' % (index, product.name, price_txt, ref))
            if include_description and product.description_sale:
                desc = product.description_sale.strip()
                if desc:
                    lines.append('   %s' % desc[:200])
        lines.extend(['', _('Contact us for ordering.')])
        message = '\n'.join(lines)
        _logger.debug('Built catalog message for %s product(s)', len(products))
        return message

    def get_products_with_images(self, products):
        """Return products that have an image, skipping others safely."""
        with_image = products.filtered(lambda p: p.image_1920)
        skipped = products - with_image
        for product in skipped:
            _logger.debug('Skipping product %s (%s): no image', product.id, product.name)
        return with_image

    def product_to_attachment(self, product, res_model=None, res_id=None):
        """Create a temporary ir.attachment from product image."""
        if not product.image_1920:
            return self.env['ir.attachment']
        name = '%s.jpg' % (product.default_code or product.name or 'product')
        model_name = res_model or 'product.template'
        model_id = res_id or product.id
        existing = self.Attachment.search([
            ('name', '=', name[:128]),
            ('res_model', '=', model_name),
            ('res_id', '=', model_id),
            ('mimetype', '=', 'image/jpeg'),
        ], limit=1)
        image = product.image_1920
        if existing and existing.raw and bytes(existing.raw) == bytes(image):
            return existing
        attachment = self.Attachment.create({
            'name': name[:128],
            'type': 'binary',
            'raw': image,
            'mimetype': 'image/jpeg',
            'res_model': model_name,
            'res_id': model_id,
        })
        _logger.debug('Created attachment %s for product %s', attachment.id, product.name)
        return attachment

    def build_product_caption(self, product, index=None):
        """Short caption for a single product image."""
        currency = self.env.company.currency_id
        symbol = currency.symbol or ''
        prefix = '%s. ' % index if index else ''
        price_txt = '%s %s' % (product.list_price, symbol) if symbol else str(product.list_price)
        ref = (' [%s]' % product.default_code) if product.default_code else ''
        return '%s%s - %s%s' % (prefix, product.name, price_txt, ref)

    def prepare_send_plan(
        self,
        products,
        use_product_images=False,
        include_product_description=False,
        include_description=None,
        **kwargs,
    ):
        """
        Build send plan: catalog text + optional per-product image sends.

        Returns dict: message, attachments (recordset), product_image_steps (list of dicts)
        """
        if include_description is not None:
            include_desc = include_description
        else:
            include_desc = include_product_description

        products = products.exists()
        if not products:
            return {'message': '', 'attachments': self.env['ir.attachment'], 'product_image_steps': []}

        message = self.build_catalog_message(products, include_description=include_desc)
        attachments = self.env['ir.attachment']
        steps = []

        if use_product_images:
            bind_model = kwargs.get('res_model') or 'product.template'
            bind_res_id = kwargs.get('res_id')
            products_with_images = self.get_products_with_images(products)
            for index, product in enumerate(products_with_images, start=1):
                att = self.product_to_attachment(
                    product,
                    res_model=bind_model,
                    res_id=bind_res_id or product.id,
                )
                if att:
                    attachments |= att
                    steps.append({
                        'product': product,
                        'attachment': att,
                        'caption': self.build_product_caption(product, index),
                    })
        return {
            'message': message,
            'attachments': attachments,
            'product_image_steps': steps,
        }

    def validate_products(self, products):
        if not products:
            raise UserError(_('Please select at least one product.'))
