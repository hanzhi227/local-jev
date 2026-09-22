"""Rank feed items using explicit relevance and substance rubrics."""

from .questions import score


def feed_request(item, interests):
    return {
        "state": {"interests": interests, "post": item},
        "questions": {
            "relevance": score(
                "Rate this post's relevance to the supplied interests.",
                ["Unrelated", "Partly relevant", "Directly relevant"],
            ),
            "substance": score(
                "Rate the concrete evidence or actionable detail in this post.",
                ["None", "Some detail", "Specific useful evidence or steps"],
            ),
            "promotion": {
                "type": "noul",
                "instructions": "The primary purpose of this post is advertising or engagement bait.",
            },
        },
    }


def feed_result(item, answers):
    # An explicit preference formula, not a calibrated probability of usefulness.
    merit = (
        answers["relevance"]["score"]
        + answers["substance"]["score"]
        - 2 * answers["promotion"]["noul"]
    )
    return {
        "post": item,
        "rank_score": round(merit, 3),
        "suggestion": "highlight"
        if merit >= 2
        else "skim"
        if merit >= 0
        else "collapse",
        "answers": answers,
    }
