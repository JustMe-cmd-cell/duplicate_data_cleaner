# -*- coding: utf-8 -*-
"""
duplicate_scanner.py
====================
Core engine for detecting and merging duplicate records.

Detection strategy:
  1. Email exact match  – fastest, SQL GROUP BY
  2. Phone normalised match – SQL after stripping non-digits
  3. Name similarity – Python Levenshtein over batches (avoid full N² scan)

Merge strategy:
  - Re-link all FK references from duplicates → master via _remap_records
  - Archive (soft-delete) the duplicate records
  - Store a JSON snapshot in merge history for undo
"""
import json
import logging
from collections import defaultdict

from odoo import models, api, _
from odoo.exceptions import UserError
from .utils import normalize_phone, name_similarity_score

_logger = logging.getLogger(__name__)

# Minimum name similarity to consider two names duplicates
NAME_SIMILARITY_THRESHOLD = 0.82

# Maximum number of records to compare pairwise in name scan
# to avoid O(N²) on very large tables
NAME_SCAN_BATCH_SIZE = 2000


class DuplicateScanner(models.AbstractModel):
    """
    Abstract model providing scanning and merging utilities.
    Called by cron jobs and by the UI.
    """
    _name = 'duplicate.scanner'
    _description = 'Duplicate Scanner Engine'

    # ------------------------------------------------------------------
    # Public entry-points
    # ------------------------------------------------------------------

    @api.model
    def scan_all(self):
        """
        Full scan across all supported models.
        Clears existing pending groups and re-builds them.
        Called by cron or the 'Scan for Duplicates' button.
        """
        # Remove stale pending groups before re-scanning
        self.env['duplicate.group'].search([('state', '=', 'pending')]).unlink()

        total = 0
        for model_name in ('res.partner', 'product.product'):
            total += self._scan_model(model_name)

        _logger.info('Duplicate scan complete – %d groups created.', total)
        return total

    @api.model
    def _scan_model(self, model_name):
        """Run all detection methods for a single model."""
        created = 0
        created += self._detect_by_email(model_name)
        created += self._detect_by_phone(model_name)
        created += self._detect_by_name(model_name)
        return created

    # ------------------------------------------------------------------
    # Detection methods
    # ------------------------------------------------------------------

    @api.model
    def _detect_by_email(self, model_name):
        """
        Find records sharing the same non-empty email (exact match).
        Uses a single SQL GROUP BY query for performance.
        Only runs on models that actually have an email field.
        """
        model_obj = self.env[model_name]
        if 'email' not in model_obj._fields:
            return 0

        table = model_obj._table
        cr = self.env.cr

        active_clause = "AND active = TRUE" if 'active' in model_obj._fields else ""
        cr.execute(f"""
            SELECT LOWER(TRIM(email)) AS email, ARRAY_AGG(id ORDER BY id) AS ids
            FROM {table}
            WHERE email IS NOT NULL
              AND email != ''
              {active_clause}
            GROUP BY LOWER(TRIM(email))
            HAVING COUNT(*) > 1
        """)
        rows = cr.fetchall()
        return self._create_groups_from_rows(model_name, rows, 'email', 1.0)

    @api.model
    def _detect_by_phone(self, model_name):
        """
        Find records with the same normalised phone number.
        Normalisation strips all non-digit characters.
        Only runs on models that have a phone field.
        """
        model_obj = self.env[model_name]
        if 'phone' not in model_obj._fields:
            return 0

        table = model_obj._table
        cr = self.env.cr
        active_clause = "AND active = TRUE" if 'active' in model_obj._fields else ""

        cr.execute(f"""
                SELECT id, phone FROM {table}
                WHERE phone IS NOT NULL AND phone != '' {active_clause}
            """)

        rows = cr.fetchall()
        phone_map = defaultdict(list)
        for rec_id, phone in rows:
            key = normalize_phone(phone)
            if key:
                phone_map[key].append(rec_id)

        clusters = [(key, ids) for key, ids in phone_map.items() if len(ids) > 1]
        return self._create_groups_from_rows(model_name, clusters, 'phone', 0.95)

    @api.model
    def _detect_by_name(self, model_name):
        """
        Find records whose names are highly similar (fuzzy match).
        To stay performant we:
          1. Fetch at most NAME_SCAN_BATCH_SIZE records per model.
          2. Sort by name so similar names are adjacent (quick wins).
          3. Run O(N*k) comparisons with a sliding window of size ~20.
        """
        model_obj = self.env[model_name]

        # Skip models where 'name' is not a column stored in this model's own table
        # (e.g. product.product.name is a related field on product.template)
        name_field = model_obj._fields.get('name')
        if not name_field or name_field.related or name_field.compute:
            return 0

        table = model_obj._table
        cr = self.env.cr
        active_clause = "AND active = TRUE" if 'active' in model_obj._fields else ""

        cr.execute(f"""
            SELECT id, name FROM {table}
            WHERE name IS NOT NULL AND name != '' {active_clause}
            ORDER BY LOWER(name)
            LIMIT {NAME_SCAN_BATCH_SIZE}
        """)
        rows = cr.fetchall()

        if len(rows) < 2:
            return 0

        # Sliding window: compare each record against the next 20 in sorted order
        window = 20
        clusters = {}  # representative_id -> set of duplicate ids

        def get_root(n, parent):
            while parent.get(n, n) != n:
                n = parent[n]
            return n

        parent = {}  # union-find for grouping

        for i, (id1, name1) in enumerate(rows):
            for j in range(i + 1, min(i + window, len(rows))):
                id2, name2 = rows[j]
                score = name_similarity_score(name1, name2)
                if score >= NAME_SIMILARITY_THRESHOLD:
                    root1 = get_root(id1, parent)
                    root2 = get_root(id2, parent)
                    if root1 != root2:
                        parent[root2] = root1

        # Build cluster dict
        group_map = defaultdict(set)
        for rec_id, _ in rows:
            root = get_root(rec_id, parent)
            group_map[root].add(rec_id)

        created = 0
        for root, members in group_map.items():
            if len(members) < 2:
                continue
            # Confidence is the average pairwise similarity within the cluster
            member_list = list(members)
            name_map = dict(rows)
            scores = [
                name_similarity_score(name_map.get(a, ''), name_map.get(b, ''))
                for idx, a in enumerate(member_list)
                for b in member_list[idx + 1:]
            ]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            cluster_rows = [('', member_list)]
            created += self._create_groups_from_rows(
                model_name, cluster_rows, 'name', avg_score
            )

        return created

    # ------------------------------------------------------------------
    # Group creation helper
    # ------------------------------------------------------------------

    @api.model
    def _create_groups_from_rows(self, model_name, rows, method, base_confidence):
        """
        Create duplicate.group + duplicate.record entries for each cluster.
        Skips clusters that already exist as a pending group.
        """
        Group = self.env['duplicate.group']
        DupRecord = self.env['duplicate.record']
        created = 0

        for _key, ids in rows:
            if len(ids) < 2:
                continue

            # Check if an identical group already exists (avoid duplicating groups)
            existing = Group.search([
                ('model_name', '=', model_name),
                ('detection_method', '=', method),
                ('state', '=', 'pending'),
            ])
            existing_sets = []
            for eg in existing:
                existing_sets.append(frozenset(eg.record_ids.mapped('record_id')))
            if frozenset(ids) in existing_sets:
                continue

            # Fetch display names for the records
            records = self.env[model_name].browse(ids).exists()
            if len(records) < 2:
                continue

            group = Group.create({
                'model_name': model_name,
                'detection_method': method,
                'confidence_score': base_confidence,
                'state': 'pending',
            })

            for rec in records:
                vals = {
                    'group_id': group.id,
                    'record_id': rec.id,
                    'record_name': rec.display_name,
                }
                if hasattr(rec, 'email'):
                    vals['record_email'] = rec.email
                if hasattr(rec, 'phone'):
                    vals['record_phone'] = rec.phone
                if hasattr(rec, 'ref'):
                    vals['record_ref'] = rec.ref
                DupRecord.create(vals)

            # Default master = oldest record (lowest id)
            group.master_record_id = min(ids)
            created += 1

        return created

    # ------------------------------------------------------------------
    # Merge logic
    # ------------------------------------------------------------------

    @api.model
    def merge_group(self, group):
        """
        Merge all duplicate.record entries in `group` into the master record.

        Steps:
          1. Validate the master record still exists.
          2. Snapshot all records for undo history.
          3. Re-link FK records (Many2one fields pointing to duplicates).
          4. Archive the duplicates.
          5. Create a merge history entry.
          6. Mark the group as merged.
        """
        model_name = group.model_name
        master_id = group.master_record_id
        master = self.env[model_name].browse(master_id).exists()
        if not master:
            raise UserError(
                _('Master record (ID %d) no longer exists.') % master_id
            )

        duplicate_ids = [
            r.record_id for r in group.record_ids
            if r.record_id != master_id
        ]

        if not duplicate_ids:
            raise UserError(_('No duplicate records to merge.'))

        duplicates = self.env[model_name].with_context(active_test=False).browse(
            duplicate_ids
        ).exists()

        # Step 1: Snapshot for undo
        snapshot = self._snapshot_records(model_name, [master] + list(duplicates))

        # Step 2: Re-link FK references
        self._remap_records(model_name, duplicate_ids, master_id)

        # Step 3: Archive duplicates (soft-delete)
        duplicates.write({'active': False})

        # Step 4: Mark duplicate.record rows as archived
        group.record_ids.filtered(
            lambda r: r.record_id != master_id
        ).write({'is_archived': True})

        # Step 5: History
        self.env['duplicate.merge.history'].create({
            'group_id': group.id,
            'model_name': model_name,
            'master_record_id': master_id,
            'master_record_name': master.display_name,
            'merged_record_ids_json': json.dumps(duplicate_ids),
            'field_values_snapshot': json.dumps(snapshot),
        })

        # Step 6: Mark group as merged
        group.write({'state': 'merged'})

        _logger.info(
            'Merged %d duplicates into %s[%d] (%s).',
            len(duplicate_ids), model_name, master_id, master.display_name,
        )

    @api.model
    def _remap_records(self, model_name, duplicate_ids, master_id):
        """
        Find all Many2one fields across the database that reference
        `model_name` and update rows pointing at any duplicate_id
        to point at master_id instead.

        We query ir.model.fields to get the list of fields, then
        issue targeted UPDATE statements per table — this is the same
        approach used by Odoo's own base_setup merge partner utility.
        """
        cr = self.env.cr

        # Find all Many2one fields that reference this model
        cr.execute("""
            SELECT f.name, m.model
            FROM ir_model_fields f
            JOIN ir_model m ON m.id = f.model_id
            WHERE f.ttype = 'many2one'
              AND f.relation = %s
              AND f.store = TRUE
        """, (model_name,))
        fields_info = cr.fetchall()

        for field_name, referring_model in fields_info:
            try:
                referring_model_obj = self.env.get(referring_model)
                if referring_model_obj is None:
                    continue
                table = referring_model_obj._table
                col = field_name

                cr.execute(f"""
                    UPDATE {table}
                    SET {col} = %s
                    WHERE {col} = ANY(%s)
                """, (master_id, duplicate_ids))

            except Exception as exc:  # pylint: disable=broad-except
                _logger.warning(
                    'Could not remap %s.%s: %s', referring_model, field_name, exc
                )

    @api.model
    def _snapshot_records(self, model_name, records):
        """Return a list of field-value dicts for all records (for undo history)."""
        snapshot = []
        for rec in records:
            try:
                fields_data = rec.read()[0]
                # Make every value JSON-serializable
                safe = {}
                for k, v in fields_data.items():
                    if isinstance(v, bytes):
                        safe[k] = v.decode('latin-1')  # preserve binary as string
                    elif hasattr(v, 'isoformat'):       # date / datetime
                        safe[k] = v.isoformat()
                    else:
                        safe[k] = v
                snapshot.append(safe)
            except Exception:  # pylint: disable=broad-except
                snapshot.append({'id': rec.id})
        return snapshot

    # ------------------------------------------------------------------
    # Dashboard stats
    # ------------------------------------------------------------------

    @api.model
    def get_dashboard_data(self):
        """Return counts for the dashboard view."""
        Group = self.env['duplicate.group']
        pending = Group.search_count([('state', '=', 'pending')])
        merged = Group.search_count([('state', '=', 'merged')])
        ignored = Group.search_count([('state', '=', 'ignored')])

        by_model = {}
        for model in ('res.partner', 'product.product'):
            by_model[model] = Group.search_count([
                ('model_name', '=', model),
                ('state', '=', 'pending'),
            ])

        history_stats = self.env['duplicate.merge.history'].get_merge_summary()

        return {
            'pending_groups': pending,
            'merged_groups': merged,
            'ignored_groups': ignored,
            'by_model': by_model,
            'history': history_stats,
        }
