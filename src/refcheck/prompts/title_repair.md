<!--
Prompt: title_repair
Purpose: Extract correct paper titles from malformed reference entries
Input variables: references_json
Output schema: TitleRepairResponse
Role: utility (model resolved by refcheck.llm roles; never hard-coded)
-->

You are a scientific reference parser. The following reference entries have malformed or missing titles.
For each one, extract the correct paper title from the raw text.

## References

{{ references_json }}

## Instructions

For each reference:
1. The title is the name of the PAPER, not the journal
2. If you cannot determine the title, return the raw text's best candidate
3. Do not invent titles — only extract what is present in the raw text
4. The title should be a complete sentence or phrase (usually 5+ words)

## Output Format

Return ONLY a JSON object:

```json
{
    "repairs": [
        {"index": 0, "title": "corrected title here"},
        {"index": 1, "title": "corrected title here"}
    ]
}
```
