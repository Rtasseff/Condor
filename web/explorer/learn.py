"""Learn page content: the sessions, the plain-words glossary, the why-card.

Copy, not computation — `/learn` is a text page over these constants, so
there are no numerics and no models here (ARCHITECTURE: views are the HTTP
boundary). Two shape decisions worth keeping:

- **Sessions are a list.** The channel grows (indices, ETFs, S&P 500,
  passive vs active are planned), so adding the next video is appending a
  dict, never writing another block of bespoke markup.
- **Glossary ids are API.** In-app "Learn →" links, and anything anyone
  bookmarks, point at `/learn#<id>`; rename one only together with its
  callers (`test_every_in_app_learn_link_resolves_to_an_anchor` pins the
  in-app half of that contract).

Video content comes from the Condor Funds YouTube channel; nothing here is
fetched at build or render time — the embeds are click-to-load facades and
the transcript is stored text.
"""

from django.urls import reverse

CHANNEL_URL = "https://www.youtube.com/@Condor_Funds"
WATCH_URL = "https://www.youtube.com/watch?v={id}"
THUMB_URL = "https://i.ytimg.com/vi/{id}/hqdefault.jpg"


def _link(label, url_name, fragment=""):
    """A link inside a sentence, resolved at render time (importing this
    module must not need the URLconf loaded)."""
    return {"label": label, "url_name": url_name, "fragment": fragment}


# --------------------------------------------------------------- glossary

GLOSSARY = [
    {
        "id": "portfolio",
        "term": "Portfolio",
        "body": "A group of assets you own, plus a decision about how much "
                "of your money sits in each one. That's it — a list and the "
                "amounts.",
        "in_app": ["your mix on ", _link("Explore", "index"),
                   " is a portfolio the moment it has one asset."],
    },
    {
        "id": "weight",
        "term": "Weight",
        "body": "One asset's share of your total money. All the weights "
                "together add up to 100%.",
        "in_app": ["the pie on ", _link("Explore", "index"),
                   ", and the sliders on ", _link("Optimize", "optimize"), "."],
    },
    {
        "id": "diversification",
        "term": "Diversification",
        "body": "Spreading your money over many assets that don't all fail "
                "together. It keeps returns reasonable while lowering the "
                "damage any single asset can do — the video's house with "
                "many supports instead of one or two.",
    },
    {
        "id": "expected-return",
        "term": "Expected return",
        "body": "Our estimate, from an asset's own history, of how it "
                "typically grows in a year. An estimate is a best guess, "
                "never a promise.",
    },
    {
        "id": "dispersion",
        "term": "Dispersion",
        "body": "How widely returns swing around their middle — our word "
                "for risk. Two mixes can have the same expected return "
                "while one is a much wilder ride.",
    },
    {
        "id": "robust",
        "term": "Robust statistics",
        "body": "Medians and other outlier-resistant measures instead of "
                "plain averages, so a few wild days in history don't "
                "dominate the picture. It's about how we measure history — "
                "not a prediction that the economy will be robust.",
    },
    {
        "id": "frontier",
        "term": "Efficient frontier",
        "body": "For every level of dispersion there's a best-possible "
                "expected return; drawn together they form the curve on "
                "Optimize. Mixes below the curve leave return on the table "
                "for the risk taken.",
    },
    {
        "id": "cal",
        "term": "Cash and the straight line",
        "body": "Mix the best risky portfolio with cash and your options "
                "trace a straight line on the chart — more cash slides you "
                "toward safety, less slides you up the line. The touching "
                "point is the best all-risky mix.",
    },
    {
        "id": "index",
        "term": "Index (like the S&P 500)",
        "body": "A stock portfolio built by a public rule rather than a "
                "manager's picks. The S&P 500 tracks roughly 500 large US "
                "companies; buying an index fund is buying that whole list "
                "in one purchase.",
    },
    {
        "id": "bond",
        "term": "Bonds and T-bills",
        "body": "Lending money — to the US government, in a T-bill's case — "
                "for a modest, steady payback. The video's fortress: very "
                "safe, and a bit boring on its own.",
    },
    {
        "id": "whole-shares",
        "term": "Whole shares",
        "body": "Real accounts buy whole shares, so your target mix gets "
                "rounded to what's actually buyable.",
        "in_app": ["the trade report on ", _link("My portfolio", "account"),
                   " shows exactly what to buy or sell to get as close as "
                   "possible."],
    },
    {
        "id": "bands",
        "term": "Forecast bands",
        "body": "We simulate many possible futures for your mix; the bands "
                "show where most of them land. They're wide on purpose — a "
                "narrow promise would be a lie.",
    },
    {
        "id": "anchor",
        "term": '"Return to normal"',
        "body": "An Advanced forecast setting: instead of trusting your "
                "mix's own history alone, blend it toward a long-run market "
                "assumption (about 8% a year) or a number you choose.",
        "in_app": ['"What to assume about returns" on the ',
                   _link("forecast card", "optimize", "#forecastcard"), "."],
    },
]


# --------------------------------------------------------------- sessions

SESSIONS = [
    {
        "id": "what-is-a-portfolio",
        "title": "What is a portfolio?",
        "length": "3:25",
        "video_id": "dyjYgHEM1og",
        "hook": "A house by the sea, held up by supports — the whole idea "
                "of a portfolio in three minutes.",
        "covers": ["portfolio", "weight", "diversification", "index", "bond"],
        # The video's own captions, lightly punctuated for reading.
        "transcript": [
            "So you want to invest in your future. Lots of possibilities out "
            "there — we suggest a financial portfolio. Now what is that? "
            "Directly put, it is a group of financial assets that one owns. "
            "Having a diversified portfolio means you are investing in many "
            "different financial assets: it helps maintain reasonable returns "
            "on investments, but lowers the risk — if some go bad, you have "
            "others. A portfolio is a set of assets and an amount, or "
            "percentage, otherwise called a weight, on each of these assets.",

            "Let's say you buy a small house over the ocean. There is "
            "probably a bit of erosion, so you get the experts over, and they "
            "say you can get two supports to help hold up the house. This "
            "gives you extra money to buy great furniture, a big TV, "
            "electronics and a lot of fun stuff. The experts don't give you "
            "any guarantee on what might happen in the future — just their "
            "best guess. Now, one bad storm and everything falls apart; you "
            "could lose everything. You can invest in a fortress instead, "
            "that will never break — but now you invest all this money and "
            "your house is going to be empty and rather boring. Now there is "
            "something in between: you could get many different supports. You "
            "may not have as many cool things in the house, but you can have "
            "some, and it is fairly safe. One support breaks? Then you have "
            "time to either replace it or repair it.",

            "Let's continue this from a more specific financial view. Think "
            "of the fortress as a bond — specifically a US treasury bill. It "
            "is basically risk-free, but you invest, say, $10,000 and after "
            "20 years you probably get two or three thousand dollars back in "
            "profit. A boring prospect within a boring room. Now let's say "
            "you're a bit more adventurous, so you go into stocks — maybe one "
            "or two supports. Maybe experts tell you what to expect; maybe "
            "you even have good data. Whatever it is, guessing one or two "
            "stock prices is high risk — there's definitely more to learn on "
            "this, but that's for another session. Bottom line: the stock is "
            "probably 50/50 up or down. It could even go bankrupt, and then "
            "you get nothing — your house crashing into the water.",

            "But you can invest in many stocks at once — a stock portfolio — "
            "basically betting on the whole US economy, not one company. Of "
            "course there are ups and downs even across the whole economy, "
            "but long term the US economy has always gone up. As an "
            "educational example, the S&P 500 is an index — a type of stock "
            "portfolio made up of about 500 companies; more information on "
            "that in another session. The bottom line is, it shows that over "
            "the last 100 years the market goes up and down, but on average, "
            "in the long term, it goes up — and over 10 or 20 years it goes "
            "up a lot more than one single bond. And through every financial "
            "crisis we have, it still goes up, given enough time.",

            "Even though it may not feel like it, the US economy has a chance "
            "for an everybody-wins scenario — because the US economy "
            "constantly grows. The only real problem is getting all good "
            "working people the right tools and opportunities to take part in "
            "that growth. Now, your portfolio can include lots of "
            "opportunities for diversification: many combinations of US "
            "stocks, international stocks, bonds, commodities. There are "
            "several other sessions and external sources we can point you to "
            "for more information — on assets, stock indices, "
            "diversification, and the possible downside of current services, "
            "including large investment banks and hedge funds.",
        ],
    },
]


# -------------------------------------------------------------- why-card

WHY = {
    "title": "The Founder of Condor Funds on how the project came to be.",
    "length": "30:16",
    "video_id": "jT6muQRTAeI",
    "line": "A 30-minute conversation with the founder about why this "
            "project exists.",
    "quotes": [
        "They want to make it sound complicated, because their jobs depend "
        "on the fact that they know it and you don't.",
        "We meet them where they're at, we show them with actual data — and "
        "if they want to dig in more technically, they can.",
    ],
}


# --------------------------------------------------------------- assembly

def _resolve(parts):
    """Sentence parts -> the same list with `href` filled on the links."""
    out = []
    for part in parts:
        if isinstance(part, dict):
            part = dict(part, href=reverse(part["url_name"]) + part["fragment"])
        out.append(part)
    return out


def _video(item):
    """The facade's two URLs. The embed URL is deliberately absent: the
    click-to-load script builds it from the id, so a page that has not been
    clicked carries no YouTube player URL at all."""
    return {"thumb": THUMB_URL.format(id=item["video_id"]),
            "watch": WATCH_URL.format(id=item["video_id"])}


def learn_context():
    """Template context for `/learn` — the whole page is these three keys."""
    terms = {entry["id"]: entry["term"] for entry in GLOSSARY}
    sessions = [
        dict(session, **_video(session),
             covers=[{"id": cid, "term": terms[cid]} for cid in session["covers"]])
        for session in SESSIONS
    ]
    glossary = [
        dict(entry, in_app=_resolve(entry["in_app"])) if entry.get("in_app")
        else entry
        for entry in GLOSSARY
    ]
    return {"sessions": sessions, "glossary": glossary,
            "why": dict(WHY, **_video(WHY)), "channel_url": CHANNEL_URL}
