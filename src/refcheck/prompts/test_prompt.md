<!--
Prompt: test_prompt
Purpose: Test prompt for unit testing
Input variables: topic
Output schema: any JSON object
-->

# Task

Write a brief response about {{ topic }}.

# Output Format

Return ONLY a JSON object with these fields:
{
  "summary": "string",
  "confidence": 0.0-1.0
}
