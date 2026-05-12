"""Prompts for edge-case generation factories."""

FIRST_EDGE_CASE_PROMPT = (
    "Generate the next edge case. Use local read-only context tools only when "
    "needed, then call provide_case with the complete Case object."
)

EDGE_CASE_AGENT_INSTRUCTIONS = (
    "You generate edge cases for Rue tests. Analyze the test and provide Case "
    "values that have the highest chance of failing assertions in the test "
    "body while still being valid for the described inputs and references. "
    "Local context tools are read-only: use ls, read_file, glob, and grep "
    "when needed. Writing, editing, shell execution, and dependency graph "
    "tools are unavailable. If the conversation history grows large, call "
    "compact_conversation with the attempt strategy or constraint that must "
    "be preserved. Call provide_case with a complete Case object when ready.\n"
    "Local dependency file tree:\n{test_deps}\n"
    "Test code body: {test_code_body}\n"
    "Case JSON schema: {case_schema}"
)

EDGE_CASE_REVIEW_INSTRUCTIONS = (
    "Check whether proposed Case values are valid for the test description "
    "and schema. Reject invalid, missing, or impossible values even if they "
    "might fail the test.\n"
    "Test code body:{test_code_body}\n"
    "Case JSON schema:{case_schema}"
)

EDGE_CASE_SUMMARY_PROMPT = """\
<role>
Rue edge-case generation memory compressor
</role>

<primary_objective>
Preserve the information needed to keep generating new valid adversarial Case
attempts without repeating already tried ideas.
</primary_objective>

<instructions>
Extract durable context from the older conversation history. Keep:
- the kinds of edge-case attempts already tried
- concrete proposed Case values when they matter
- review rejection reasons and validation constraints
- execution outcomes observed after accepted attempts
- durable facts discovered through local read-only tools
- promising untried directions implied by the history

Do not include stale limit warnings, generic tool chatter, or irrelevant file
contents. Respond only with the compressed memory.
</instructions>

<messages>
{messages}
</messages>
"""
