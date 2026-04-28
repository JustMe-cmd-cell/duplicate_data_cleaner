# -*- coding: utf-8 -*-
{
    'name': 'Duplicate Data Cleaner',
    'version': '17.0.1.0.0',
    'category': 'Tools',
    'summary': 'Detect, review, and merge duplicate contacts, companies, and products',
    'description': """
Duplicate Data Cleaner
======================
Automatically detects duplicate records in your Odoo database and provides
a simple interface to review and merge them.

Features:
- Duplicate detection by email, phone, and name similarity (fuzzy matching)
- Side-by-side comparison with field difference highlighting
- Field-level merge control (choose which values to keep)
- Bulk merge operations
- Merge history and undo support
- Scheduled automatic scans
- Confidence scoring
- Dashboard with duplicate statistics
    """,
    'author': 'Odoo Premium',
    'depends': ['base', 'mail', 'product', 'web'],
    'data': [
        'security/duplicate_cleaner_groups.xml',
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'views/duplicate_group_views.xml',
        'views/duplicate_merge_history_views.xml',
        'views/duplicate_dashboard_views.xml',
        'views/menus.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'duplicate_data_cleaner/static/src/js/duplicate_comparison_widget.js',
            'duplicate_data_cleaner/static/src/xml/duplicate_comparison_widget.xml',
            'duplicate_data_cleaner/static/src/css/duplicate_cleaner.css',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'price': 150.0,
    'currency': 'EUR',
    'images': ['static/description/banner.png'],
}
