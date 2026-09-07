# Runtime dependency ban

**Google Cloud AI only, at runtime.**

Permitted packages (imported and actually called):
- `google-adk`
- `google-genai`
- `google-generativeai`
- `google-cloud-aiplatform`

**Banned — disqualifies the entry if present anywhere in the dependency tree:**
- `openai`
- `anthropic`
- Any AWS AI SDK (`boto3` AI calls, `amazon-bedrock-*`, etc.)
- Any Microsoft AI SDK (`azure-cognitiveservices-*`, `openai` via Azure, etc.)

**Before every push, verify:**

```bash
grep -r "openai\|anthropic\|bedrock\|azure.cognitiveservices" \
  requirements.txt pyproject.toml agents/ --include="*.py" --include="*.txt" --include="*.toml"
```

This check must return no matches. If it does, fix before pushing.
A stray SDK import is a disqualifier — not a warning, not a TODO.
