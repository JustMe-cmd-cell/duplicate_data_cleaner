# -*- coding: utf-8 -*-
import json
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DuplicateMergeHistory(models.Model):
    """
    Audit trail for every merge operation.
    Stores enough information to undo a merge by re-creating
    the archived records and restoring their relationships.

    NOTE: Full undo is complex because re-linked FK records cannot be
    automatically moved back without knowing the pre-merge state.
    We store a JSON snapshot so an admin can manually recover data.
    For automated undo we support: unarchiving the duplicate records
    and detaching them from the master (effectively reversing the
    archive step for soft-deleted records).
    """
    _name = 'duplicate.merge.history'
    _description = 'Merge History'
    _order = 'merge_date desc'

    group_id = fields.Many2one(
        comodel_name='duplicate.group',
        string='Duplicate Group',
        ondelete='set null',
    )
    model_name = fields.Char(string='Model', required=True)
    master_record_id = fields.Integer(string='Master Record ID', required=True)
    master_record_name = fields.Char(string='Master Record Name')
    merged_record_ids_json = fields.Text(
        string='Merged Record IDs (JSON)',
        help='JSON list of record IDs that were merged and archived.',
    )
    field_values_snapshot = fields.Text(
        string='Field Values Snapshot (JSON)',
        help='JSON snapshot of all merged records before the operation. '
             'Used for manual recovery.',
    )
    merge_date = fields.Datetime(
        string='Merge Date',
        default=fields.Datetime.now,
    )
    performed_by = fields.Many2one(
        comodel_name='res.users',
        string='Performed By',
        default=lambda self: self.env.user,
    )
    state = fields.Selection(
        selection=[('done', 'Done'), ('undone', 'Undone')],
        default='done',
        string='State',
    )

    def action_undo(self):
        """
        Undo a merge by unarchiving the previously merged records
        and resetting the duplicate group back to 'pending'.
        Relationship re-linking is NOT reversed automatically
        (that would require a full transactional snapshot).
        A warning is shown to the user.
        """
        self.ensure_one()
        if self.state == 'undone':
            raise UserError(_('This merge has already been undone.'))

        merged_ids = json.loads(self.merged_record_ids_json or '[]')
        if not merged_ids:
            raise UserError(_('No merged record IDs stored. Cannot undo.'))

        records = self.env[self.model_name].with_context(active_test=False).browse(merged_ids)
        existing = records.exists()
        existing.write({'active': True})

        # Reset group state so users can review again
        if self.group_id:
            self.group_id.write({'state': 'pending', 'master_record_id': False})

        self.write({'state': 'undone'})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Merge Undone'),
                'message': _(
                    '%d records have been unarchived. Note: re-linked relationships '
                    '(invoices, sales orders, etc.) were NOT reversed automatically. '
                    'Please verify the data manually.'
                ) % len(existing),
                'type': 'warning',
                'sticky': True,
            },
        }

    @api.model
    def get_merge_summary(self):
        """Return dashboard statistics for the last 30 days."""
        self.env.cr.execute("""
            SELECT COUNT(*) AS total_merges,
                   COUNT(DISTINCT model_name) AS models_affected,
                   SUM(
                       COALESCE(json_array_length(merged_record_ids_json::json), 0)
                   ) AS records_merged
            FROM duplicate_merge_history
            WHERE merge_date >= NOW() - INTERVAL '30 days'
              AND state = 'done'
        """)
        row = self.env.cr.fetchone()
        return {
            'total_merges': row[0] or 0,
            'models_affected': row[1] or 0,
            'records_merged': row[2] or 0,
        }
