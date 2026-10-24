{#-
Prompt: llm_json_retry
Purpose: Correction turn sent by refcheck.llm.client when a reply was not valid JSON for the schema
Input variables: error
Output schema: the caller's schema
#}
Your previous reply could not be used: {{ error }}

Reply again with ONLY one JSON object that matches the requested schema exactly. No markdown fences, no text before or after the JSON.
