# Commit discipline

- **Commit only after Alami approves a step.**
- One commit per approved step. Push immediately.
- Use Bob's commit message generation.
- Every commit must carry these trailers, each on its own line:

```
Built-with: IBM-Bob
Co-authored-by: IBM Bob <bob@ibm.com>
```

No exceptions. Both trailers are required. This is track-qualifying evidence.

The public repo history should show the build progressing in approved increments.
One enormous dump on Tuesday night is the failure mode to avoid.
