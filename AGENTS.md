# Code Patterns
- Don't do defensive programming. Try-catch are acceptible only after having approval from the user.
- Follow OOP and DRY everywhere except tests, evals and QA.
- For tests use Rue if the file starts with 'rue_*.py'. Docs are in /docs.
- Keep code short. Smaller is better.
- No method-level imports. All imports should be at the top of the file.

# Tools
- use 'uv' instead of 'pip' for package management
    - 'uv add toolname' instead of 'pip install toolname'
    - 'uv run script' instad of 'python script' or 'script'
