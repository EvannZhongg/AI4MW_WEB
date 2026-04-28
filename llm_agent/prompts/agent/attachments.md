Current user turn includes uploaded images.

Available attachment names: {{ attachment_names }}.

If line chart extraction is needed, prefer `extract_line_chart`. You may omit `image_path`; the backend will resolve the current-turn image automatically. For multimodal gateway compatibility, prior assistant messages may be omitted when current-turn images are present; focus on the user's text history and the uploaded images.
