def render_text(briefing):
    """Turn a structured Briefing into plain text for the command line."""
    lines = [briefing.overview, ""]
    for theme in briefing.themes:
        lines.append(theme.title)
        for bullet in theme.bullets:
            lines.append(f"- {bullet.text}")
            lines.append(f"  Sources: {', '.join(bullet.sources)}")
        lines.append("")
    lines.append(f"Worth watching: {briefing.worth_watching}")
    return "\n".join(lines)
