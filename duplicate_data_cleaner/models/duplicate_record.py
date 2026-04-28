# -*- coding: utf-8 -*-
from odoo import models, fields, api


class DuplicateRecord(models.Model):
    """
    Represents a single record that belongs to a duplicate group.
    Stores a snapshot of key field values at detection time for
    fast side-by-side comparison without hitting the source model.
    """
    _name = 'duplicate.record'
    _description = 'Duplicate Record Entry'
    _order = 'group_id, is_master desc, id'

    group_id = fields.Many2one(
        comodel_name='duplicate.group',
        string='Duplicate Group',
        required=True,
        ondelete='cascade',
        index=True,
    )
    record_id = fields.Integer(
        string='Source Record ID',
        required=True,
        index=True,
    )
    record_name = fields.Char(string='Name', index=True)
    record_email = fields.Char(string='Email')
    record_phone = fields.Char(string='Phone')
    record_ref = fields.Char(string='Reference')
    is_master = fields.Boolean(
        string='Is Master',
        default=False,
        help='If True, this record will be kept during merge.',
    )
    is_archived = fields.Boolean(
        string='Archived after merge',
        default=False,
    )

    @api.model
    def _get_record_display(self, model_name, record_id):
        """Return a dict of display fields for a given record."""
        record = self.env[model_name].browse(record_id).exists()
        if not record:
            return {}
        data = {'id': record.id, 'name': record.display_name}
        if hasattr(record, 'email'):
            data['email'] = record.email
        if hasattr(record, 'phone'):
            data['phone'] = record.phone
        if hasattr(record, 'ref'):
            data['ref'] = record.ref
        return data
