meta = {
    "name": "reviewed-workflow",
    "description": "Run the canonical reviewed workflow from planning through evidence-backed reporting.",
    "whenToUse": "Use for a substantial objective that should be decomposed, executed by scoped workers, independently reviewed, repaired within limits, integrated only after PASS, finally validated, and reported with evidence.",
    "phases": [
        {"title": "Planning"},
        {"title": "Execution"},
        {"title": "Review"},
        {"title": "Repair"},
        {"title": "Final Validation"},
        {"title": "Reporting"},
    ],
}

return await reviewed_workflow(args)
