# Baseline extraction and compatibility audit

Date: 2026-10-22

This directory is a source-level extraction of the internally consistent 1.0.0 package inside the root archive `ChatGPT_Blender_Bridge.zip` (Git blob SHA `5442325f1afe7a53f0546fc75371359c38c2e00a`, archive size 71590 bytes).

## What was done
- Preserved the original ZIP on `main`; no files on `main` were changed.
- Extracted the inner 1.0.0 source files to a normal, browsable directory structure.
- Basic integrity checks passed for selected ZIP entries: the extracted byte lengths match the ZIP central-directory sizes.
- Version sanity checks passed for the Add-on `bl_info` (1.0.0), Blender extension manifest (1.0.0), and tool schema count (19).
- The separate add-on installer ZIP was copied byte-for-byte from the outer archive.

## Version discrepancy found in the original archive
The archive also contains a second, top-level set of files whose `README_DE.md` identifies version 1.1.0 and whose MCP server files differ from the nested 1.0.0 package. However, the Blender add-on source and extension manifest in the archive still declare 1.0.0. This branch deliberately labels and preserves the consistent 1.0.0 set as a baseline; it does not pretend the mixed 1.1.0 files form a verified release.

## Not yet verified
- No code was executed inside Blender.
- No real local connection to the user's Blender process was made.
- No ChatGPT desktop/Work/Codex end-to-end MCP connection was tested.
- No new unified 1.1.0 release was created.

Next work should compare the newer HTTP/stdio server files against the 1.0.0 add-on's tool behavior, add automated protocol/security tests, and only then assign a unified version number.
