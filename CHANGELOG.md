# Changelog

## v2026.11.16.001 - 2026-11-16

Checked against Open WebUI 0.13.3. Versions now follow `v{YYYY}.{MM}.{DD}.{NNN}`.

### Added

- Read/Write MCP tool annotations on every tool (`readOnlyHint`, `destructiveHint`).
- `get_model_history`: earlier saved versions of a model's settings.
- `get_config_namespace`, `get_config_values`, `set_config_values`: read and change
  named settings; each change is read back, unknown keys and MFA keys are refused.
- `update_tool_server`: change one tool server (on/off, name, description, URL,
  tool filter) while every other connection stays as stored.
- `update_model` takes `params_patch` and `meta_patch` for any model parameter or
  meta field; untouched fields stay as stored.
- `WEBUI_URL` / `WEBUI_API_KEY` accepted as well as `OPENWEBUI_URL` / `OPENWEBUI_API_KEY`.

### Fixed

- A path Open WebUI does not serve now raises an error instead of returning its
  web app's HTML page as if it were a result.
- `get_current_user` returns the caller's permissions: Open WebUI answers an API key
  on `GET /api/v1/auths/` with 403 by design (browser sessions only).
- `get_model` works for connection models with no saved settings (returns their live
  entry), and the first `update_model` on such a model creates its record.
- Credentials (API keys, bearer keys, headers, secrets) are masked in every config,
  connection and tool-server result.

## Unreleased

### Changed

- Replaced `add_knowledge_text` with unified `add_knowledge_file` supporting
  text uploads, base64 binary uploads, and attaching existing Open WebUI files
  by `file_id`.

### Fixed

- Uploads that include `knowledge_id` now pass `metadata.knowledge_id` on file
  creation so Open WebUI links synchronously instead of racing a second attach
  call.

## 0.2.0 - 2026-09-05

### Added

- Added access sharing for knowledge bases through the MCP management tool.
- Added file upload support with optional knowledge-base linking.
- Added discovery of effective provider, base, and custom models.

### Fixed

- Followed pagination for users, files, and knowledge bases.
- Avoided downloading extracted file content during file listings.
- Corrected system configuration lookup to use Open WebUI's export endpoint.
- Aligned management routes with current Open WebUI APIs.
- Encoded query parameters and resource IDs safely.
- Forwarded authenticated Open WebUI session tokens correctly for scoped profiles.

