{
    'name': 'Migration Diagnostic',
    'version': '17.0.1.0.0',
    'summary': 'Odoo migration feasibility audit — complexity score and data-volume report',
    'author': 'Expodo',
    'website': 'https://expodo.fr',
    'category': 'Technical',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'base_setup'],
    'data': [
        'security/ir.model.access.csv',
        'data/risk_rules_data.xml',
        'wizard/migration_scan_wizard_views.xml',
        'views/migration_diagnostic_views.xml',
        'views/menu.xml',                               # action wizard + menuitems
        'report/migration_diagnostic_report.xml',
        'report/migration_diagnostic_report_template.xml',
    ],
    'images': ['static/description/banner.png'],
    'icon': '/migration_diagnostic/static/description/icon.png',
    'installable': True,
    'application': True,
    'auto_install': False,
}
