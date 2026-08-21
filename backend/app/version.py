# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""NukeLab platform version (static fallback).

This is the checked-in fallback for builds that did not receive a version
injection (local dev, tests). It is intentionally "0.0.0-dev" — unmistakably
not a release. Real releases are identified dynamically: CI-built images get
the exact image tag via the APP_VERSION build arg, resolved through
`settings.app_version` (app/config.py).
"""

__version__ = "0.0.0-dev"
