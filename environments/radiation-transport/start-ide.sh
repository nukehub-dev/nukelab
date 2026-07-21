#!/bin/bash
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

# Start a virtual X server before launching the IDE. The conda-forge
# ParaView/VTK builds used by the nuke-ide visualizer are X11/GLX-only and
# abort with "bad X server connection" when creating a render window without
# an X connection, even for offscreen rendering. Xvfb provides that
# connection; VTK_USE_OFFSCREEN keeps windows unmapped.
Xvfb "${DISPLAY:-:99}" -screen 0 1920x1080x24 &

exec yarn --cwd /opt/nuke-ide/applications/browser theia start --hostname :: --plugins=local-dir:../../plugins
