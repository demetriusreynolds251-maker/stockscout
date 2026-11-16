"""Video links for the #learn lessons. Each lesson gets a YouTube search (always works, many videos to pick from)
plus, where we checked one, a specific free lesson from a trusted source (OIC = the options exchanges' own free school,
Option Alpha, Webull Learn)."""
from urllib.parse import quote_plus

OIC_CALLS = "https://www.optionseducation.org/videolibrary/buying-and-selling-calls"
OIC_SPREAD = "https://www.optionseducation.org/videolibrary/bull-call-spread"
OA_INTRO = "https://optionalpha.com/lessons/what-is-an-options-contract"
WB_SPREAD = "https://www.webull.com/learn/courseware/eN7pRv/Bull-Call-Spread"


def yt(q):
    return "https://www.youtube.com/results?search_query=" + quote_plus(q)


# same order as scout_movers.LESSONS
OPTIONS = [
    ("options for beginners calls and puts explained", [("Option Alpha: What is an option? (15 min)", OA_INTRO), ("OIC: Buying and selling calls", OIC_CALLS)]),
    ("option strike price explained for beginners", []),
    ("option expiration date explained weekly options", []),
    ("option time decay theta explained simply", []),
    ("how option prices work times 100 contract explained", []),
    ("bid ask spread limit order options explained", []),
    ("bull call spread explained for beginners", [("OIC: Bull call spread (video)", OIC_SPREAD), ("Webull Learn: Bull call spread", WB_SPREAD)]),
    ("call debit spread small account explained", [("OIC: Bull call spread (video)", OIC_SPREAD)]),
    ("implied volatility explained simply options", []),
    ("options before earnings IV crush explained", []),
    ("when to take profit on options debit spread", []),
    ("position sizing options small account", []),
    ("option assignment explained close before expiration spread", []),
    ("how to trade options on Webull app tutorial call spread", [("Webull Learn: Bull call spread", WB_SPREAD)]),
]

# same order as scout_chartlessons.TITLES
CHARTS = [
    "200 day moving average explained for beginners",
    "support and resistance explained for beginners",
    "stock volume explained how to read volume",
    "how to read candlestick charts for beginners",
    "stock gaps explained gap up gap down",
    "RSI indicator explained for beginners",
    "average daily move ATR explained for beginners",
]


def options_lines(i):
    q, extra = OPTIONS[i % len(OPTIONS)]
    out = [f"🎥 **Watch:** [YouTube videos on this]({yt(q)}) (pick one 5-15 min long)"]
    out += [f"🎥 [{name}]({url})" for name, url in extra]
    return out


def chart_lines(k):
    return [f"🎥 **Watch:** [YouTube videos on this]({yt(CHARTS[k % len(CHARTS)])}) (pick one 5-15 min long)"]


def library_text(lesson_titles, chart_titles):
    parts = ["**Start here (free, from the options exchanges' own school):**",
             f"• [OIC: Buying and selling calls]({OIC_CALLS})",
             f"• [OIC: Bull call spread, the trade our cards use]({OIC_SPREAD})",
             f"• [Option Alpha: What is an option? (15 min)]({OA_INTRO})",
             f"• [Webull Learn: Bull call spread]({WB_SPREAD})", "",
             "**📘 Options lessons:**"]
    parts += [f"{i + 1}. [{t}]({yt(OPTIONS[i][0])})" for i, t in enumerate(lesson_titles)]
    parts += ["", "**📊 Chart lessons:**"]
    parts += [f"{k + 1}. [{t}]({yt(CHARTS[k])})" for k, t in enumerate(chart_titles)]
    return "\n".join(parts)
