# -*- coding: utf-8 -*-
"""
controllers/main.py
===================
JSON-RPC endpoints used by the OWL components for async operations
that benefit from a dedicated HTTP route (e.g., triggering a scan
without blocking the UI via a server action).
"""
import json
from odoo import http
from odoo.http import request


class DuplicateCleanerController(http.Controller):

    @http.route(
        '/duplicate_cleaner/scan',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def trigger_scan(self):
        """
        Trigger a full duplicate scan asynchronously.
        Called from the Dashboard OWL component via JSON-RPC.
        Returns the number of new duplicate groups created.
        """
        scanner = request.env['duplicate.scanner']
        count = scanner.scan_all()
        return {'groups_created': count}

    @http.route(
        '/duplicate_cleaner/dashboard_data',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def get_dashboard_data(self):
        """Return live dashboard statistics."""
        scanner = request.env['duplicate.scanner']
        return scanner.get_dashboard_data()

    @http.route(
        '/duplicate_cleaner/merge_group',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def merge_group(self, group_id):
        """
        Merge a single duplicate group identified by `group_id`.
        The master_record_id must already be set on the group.
        """
        group = request.env['duplicate.group'].browse(int(group_id)).exists()
        if not group:
            return {'error': f'Group {group_id} not found.'}
        try:
            request.env['duplicate.scanner'].merge_group(group)
        except Exception as exc:  # pylint: disable=broad-except
            return {'error': str(exc)}
        return {'success': True}
