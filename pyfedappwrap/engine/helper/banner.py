from pyfedappwrap.engine.validate.dto import ToolFileEvaluationResultDTO


def print_banner(title: str, message: list[str]):
    content_width = max(len(title), *(len(m) for m in message))
    inner_width = content_width + 2
    border = "#" * (inner_width + 4)

    print(border)
    print(f"# {' ' * inner_width} #")
    print(f"#  {title.center(content_width)}  #")

    for line in message:
        print(f"#  {line.ljust(content_width)}  #")

    print(f"# {' ' * inner_width} #")
    print(border)


def print_validation_error_banner(results: list['ToolFileEvaluationResultDTO']):
    """Print a formatted banner displaying validation errors."""
    error_messages = []

    for result in results:
        if not result.ok:
            name_display = f'"{result.name}"' if result.name else "N/A"
            error_messages.append(f"Failed: {name_display}")
            for error in result.errors:
                error_messages.append(f"  - {error}")

    if error_messages:
        print_banner("VALIDATION ERRORS DETECTED", error_messages)
    else:
        print_banner("VALIDATION SUCCESSFUL", ["All validation checks passed."])
