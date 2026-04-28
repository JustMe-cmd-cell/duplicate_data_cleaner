# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DuplicateGroup(models.Model):
    """
    Represents a cluster of records suspected to be duplicates.
    Each group has a model type, a list of candidate records,
    and a status tracking its lifecycle.
    """
    _name = 'duplicate.group'
    _description = 'Duplicate Group'
    _order = 'confidence_score desc, id desc'

    name = fields.Char(
        string='Group Name',
        compute='_compute_name',
        store=True,
    )
    model_name = fields.Selection(
        selection=[
            ('res.partner', 'Contact / Company'),
            ('product.product', 'Product'),
        ],
        string='Model',
        required=True,
        index=True,
    )
    detection_method = fields.Selection(
        selection=[
            ('email', 'Email Match'),
            ('phone', 'Phone Match'),
            ('name', 'Name Similarity'),
        ],
        string='Detection Method',
        required=True,
    )
    confidence_score = fields.Float(
        string='Confidence Score',
        default=0.0,
        help='Score between 0 and 1 indicating how likely these are true duplicates.',
    )
    state = fields.Selection(
        selection=[
            ('pending', 'Pending Review'),
            ('merged', 'Merged'),
            ('ignored', 'Ignored'),
        ],
        string='Status',
        default='pending',
        index=True,
    )
    record_ids = fields.One2many(
        comodel_name='duplicate.record',
        inverse_name='group_id',
        string='Duplicate Records',
    )
    record_count = fields.Integer(
        string='Record Count',
        compute='_compute_record_count',
        store=True,
    )
    master_record_id = fields.Integer(
        string='Master Record ID',
        help='The ID of the record that will be kept after merge.',
    )
    merge_history_ids = fields.One2many(
        comodel_name='duplicate.merge.history',
        inverse_name='group_id',
        string='Merge History',
    )

    @api.depends('record_ids', 'model_name')
    def _compute_name(self):
        for group in self:
            if group.record_ids:
                # Use the name of the first record as the group label
                first = group.record_ids[0]
                group.name = f'[{group.model_name}] {first.record_name}'
            else:
                group.name = _('Empty Group')

    @api.depends('record_ids')
    def _compute_record_count(self):
        for group in self:
            group.record_count = len(group.record_ids)

    def action_ignore(self):
        """Mark this group as ignored – no merge needed."""
        self.write({'state': 'ignored'})

    def action_open_comparison(self):
        """Open the side-by-side comparison view for this group."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Compare Duplicates'),
            'res_model': 'duplicate.group',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'duplicate_data_cleaner.view_duplicate_group_comparison_form'
            ).id,
            'target': 'current',
        }

    def action_merge(self):
        """
        Merge all records in this group into the master record.
        Calls the scanner's merge utility which handles ORM re-linking.
        """
        self.ensure_one()
        if not self.master_record_id:
            raise UserError(_('Please select a master record before merging.'))
        if self.state == 'merged':
            raise UserError(_('This group has already been merged.'))

        scanner = self.env['duplicate.scanner']
        scanner.merge_group(self)

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------
    def action_bulk_merge(self):
        """
        Bulk merge all selected pending groups.
        Each group must have master_record_id set.
        A confirmation wizard is shown via JS; this method is the backend
        entry-point called after confirmation.
        """
        pending = self.filtered(lambda g: g.state == 'pending' and g.master_record_id)
        if not pending:
            raise UserError(
                _('No pending groups with a master record selected. '
                  'Please set a master record for each group first.')
            )
        scanner = self.env['duplicate.scanner']
        errors = []
        for group in pending:
            try:
                scanner.merge_group(group)
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(f'Group {group.id}: {exc}')

        if errors:
            raise UserError('\n'.join(errors))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bulk Merge Complete'),
                'message': _('%d duplicate groups merged successfully.') % len(pending),
                'type': 'success',
                'sticky': False,
            },
        }
