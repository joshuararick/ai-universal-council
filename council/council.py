"""The Council: every member answers in parallel, then the Chair writes one verdict."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .config import Config, Seat
from .ollama import OllamaError
from .openrouter import OpenRouterError

# The clients turn every network/API failure into one of these (keys redacted).
SEAT_ERRORS = (OpenRouterError, OllamaError)


@dataclass
class Opinion:
    seat: Seat
    answer: str | None = None
    error: str | None = None


@dataclass
class Verdict:
    question: str
    opinions: list[Opinion]
    verdict: str


CHAIR_PROMPT = """You chair the AI Universal Council. The members answered the question below.
Write the Council's verdict:
1. **Verdict** - the single best answer, in plain words.
2. **Where they agree** - short bullets.
3. **Where they disagree** - who said what, and which side you pick and why.
4. **Next steps** - 3 concrete actions max.

QUESTION:
{question}

MEMBER ANSWERS:
{answers}"""


def validate_question(question: str, max_chars: int) -> str:
    question = question.strip()
    if not question:
        raise ValueError("Ask the Council something.")
    if len(question) > max_chars:
        raise ValueError(f"Question too long ({len(question)} > {max_chars} chars).")
    return question


class Council:
    def __init__(self, config: Config, client):
        self.config = config
        self.client = client  # anything with .chat(model, messages) -> str

    def _ask(self, seat: Seat, question: str) -> Opinion:
        messages = [{"role": "user", "content": question}]
        if seat.role:
            messages.insert(
                0,
                {"role": "system", "content": f"You are the {seat.name}. {seat.role}"},
            )
        try:
            return Opinion(seat, answer=self.client.chat(seat.model, messages))
        except SEAT_ERRORS as e:  # one broken seat must not sink the whole council
            return Opinion(seat, error=str(e))

    def convene(self, question: str, on_opinion=None) -> Verdict:
        """on_opinion(opinion) is called as each member finishes (the web page uses it)."""
        question = validate_question(question, self.config.max_prompt_chars)

        def ask(seat):
            opinion = self._ask(seat, question)
            if on_opinion:
                on_opinion(opinion)
            return opinion

        # Fan out: all members at once, not one after another
        # (unless the roster caps it, e.g. local models sharing one PC's memory).
        workers = self.config.max_parallel or len(self.config.members)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            opinions = list(
                pool.map(ask, self.config.members)
            )

        answered = [o for o in opinions if o.answer]
        if not answered:
            errors = "\n".join(f"- {o.seat.name}: {o.error}" for o in opinions)
            raise RuntimeError(f"No council member could answer:\n{errors}")

        # Fan in: the Chair merges the answers into one verdict.
        answers = "\n\n".join(
            f"### {o.seat.name} ({o.seat.model})\n{o.answer}" for o in answered
        )
        chair_msg = [
            {
                "role": "user",
                "content": CHAIR_PROMPT.format(question=question, answers=answers),
            }
        ]
        try:
            verdict = self.client.chat(self.config.chair.model, chair_msg)
        except SEAT_ERRORS as e:
            verdict = f"(Chair failed: {e}) - read the member answers above."
        return Verdict(question, opinions, verdict)
