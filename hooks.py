# -*- coding: utf-8 -*-

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Migrate legacy campaign state values after upgrade."""
    cr = env.cr
    cr.execute("""
        UPDATE whatsapp_bulk_campaign
        SET state = CASE
            WHEN state = 'done' AND COALESCE(failed_count, 0) > 0 THEN 'completed_with_errors'
            WHEN state = 'done' THEN 'completed'
            WHEN state NOT IN (
                'draft', 'running', 'completed', 'completed_with_errors', 'stopped', 'failed'
            ) THEN 'completed'
            ELSE state
        END
        WHERE state IS NULL OR state NOT IN (
            'draft', 'running', 'completed', 'completed_with_errors', 'stopped', 'failed'
        )
    """)
    _logger.info('relayruntime: campaign state migration completed')
    cr.execute("""
        UPDATE whatsapp_config
        SET provider_type = 'green_api'
        WHERE provider_type IS NULL OR provider_type = ''
    """)
    _logger.info('relayruntime: provider_type migration completed')
    _migrate_legacy_single_attachments(cr)
    _rename_free_attachment_count_column(cr)
    _cleanup_wizard_stale_field_metadata(env)


def _cleanup_wizard_stale_field_metadata(env):
    """Remove orphan ir.model.fields rows that break the wizard registry/views."""
    model = env['ir.model'].search([('model', '=', 'whatsapp.bulk.send.wizard')], limit=1)
    if not model:
        return
    stale_names = ('free_attachment_count', 'attachment_count')
    stale_fields = env['ir.model.fields'].search([
        ('model_id', '=', model.id),
        ('name', 'in', stale_names),
    ])
    if stale_fields:
        stale_fields.unlink()
        _logger.info(
            'relayruntime: removed stale wizard fields %s',
            list(stale_names),
        )


def _rename_free_attachment_count_column(cr):
    """Rename campaign column after field rename to attachment_count."""
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'whatsapp_bulk_campaign'
          AND column_name = 'free_attachment_count'
        """
    )
    if not cr.fetchone():
        return
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'whatsapp_bulk_campaign'
          AND column_name = 'attachment_count'
        """
    )
    if cr.fetchone():
        cr.execute(
            """
            UPDATE whatsapp_bulk_campaign
            SET attachment_count = COALESCE(attachment_count, free_attachment_count)
            WHERE free_attachment_count IS NOT NULL
            """
        )
        cr.execute(
            "ALTER TABLE whatsapp_bulk_campaign DROP COLUMN IF EXISTS free_attachment_count"
        )
    else:
        cr.execute(
            """
            ALTER TABLE whatsapp_bulk_campaign
            RENAME COLUMN free_attachment_count TO attachment_count
            """
        )
    _logger.info('relayruntime: renamed free_attachment_count to attachment_count on campaign')


def _migrate_legacy_single_attachments(cr):
    """Copy legacy attachment_id columns into attachment_ids M2M tables."""
    migrations = (
        (
            'whatsapp_bulk_campaign',
            'whatsapp_campaign_attachment_rel',
            'campaign_id',
            'attachment_id',
        ),
        (
            'whatsapp_bulk_send_wizard',
            'whatsapp_bulk_send_wizard_attachment_rel',
            'wizard_id',
            'attachment_id',
        ),
    )
    for table, rel_table, col_left, col_right in migrations:
        cr.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = %s AND column_name = 'attachment_id'
            """,
            (table,),
        )
        if not cr.fetchone():
            continue
        cr.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_name = %s
            """,
            (rel_table,),
        )
        if not cr.fetchone():
            _logger.warning(
                'relayruntime: skip attachment migration for %s (relation %s missing)',
                table,
                rel_table,
            )
            continue
        cr.execute(
            f"""
            INSERT INTO {rel_table} ({col_left}, {col_right})
            SELECT id, attachment_id FROM {table}
            WHERE attachment_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM {rel_table} rel
                  WHERE rel.{col_left} = {table}.id
                    AND rel.{col_right} = {table}.attachment_id
              )
            """
        )
        _logger.info(
            'relayruntime: migrated legacy attachment_id on %s (%s row(s))',
            table,
            cr.rowcount,
        )
