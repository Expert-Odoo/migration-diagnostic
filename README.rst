====================
Migration Diagnostic
====================

.. |badge1| image:: https://img.shields.io/badge/licence-LGPL--3-blue.png
    :target: https://www.gnu.org/licenses/lgpl-3.0-standalone.html
    :alt: License: LGPL-3

|badge1|

Audit the feasibility of an Odoo migration in under a minute. The module scans
the current database and produces a clear, quantified decision report:
complexity score, data volumes, risk factors and a phased migration plan,
exportable as PDF.

**Read-only**: the scan never modifies your database.

Features
========

* **Module inventory** — classifies every installed module as standard Odoo,
  OCA or custom / third-party.
* **Data volumes** — counts the critical records (partners, products, orders,
  journal entries, messages, attachments).
* **Risk factors** — flags multi-company, custom fields, Python server actions,
  accounting localizations and high volumes, each with a recommendation.
* **Complexity score** — a global score from 0 to 100 and a level
  (Low / Medium / High / Critical).
* **Effort estimate** — a workload range in person-days.
* **Phased migration plan** — recommended migration order with per-model
  watch-outs, exportable as PDF.

Installation
============

Install like any Odoo module: copy ``migration_diagnostic`` into your addons
path, update the Apps list and install *Migration Diagnostic*.

Usage
=====

Open the **Migration Diagnostic** app, run a new scan from the guided wizard
(10–60 seconds depending on database size), then review the report and export
it as PDF.

Compatibility
=============

* Odoo 17.0 — Community & Enterprise
* Dependencies: ``base``, ``mail``, ``base_setup``

Bug Tracker
===========

Issues: https://github.com/Expert-Odoo/migration-diagnostic/issues

Credits
=======

Author: `Expodo <https://expodo.fr>`_

License
=======

This module is licensed under LGPL-3. See the ``LICENSE`` file for details.
