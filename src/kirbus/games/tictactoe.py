"""Tic-tac-toe — single player vs the machine."""
from __future__ import annotations

import random

from kirbus.games import BaseGame

_WINS = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),   # rows
    (0, 3, 6), (1, 4, 7), (2, 5, 8),   # cols
    (0, 4, 8), (2, 4, 6),              # diagonals
]


def _ai_move(board: list[str]) -> int:
    """Simple AI: win > block > center > corner > edge."""
    # Try to win
    for a, b, c in _WINS:
        cells = [board[a], board[b], board[c]]
        if cells.count("O") == 2 and cells.count(" ") == 1:
            return [a, b, c][cells.index(" ")]
    # Block player win
    for a, b, c in _WINS:
        cells = [board[a], board[b], board[c]]
        if cells.count("X") == 2 and cells.count(" ") == 1:
            return [a, b, c][cells.index(" ")]
    # Center
    if board[4] == " ":
        return 4
    # Corners
    corners = [i for i in (0, 2, 6, 8) if board[i] == " "]
    if corners:
        return random.choice(corners)
    # Edges
    edges = [i for i in (1, 3, 5, 7) if board[i] == " "]
    if edges:
        return random.choice(edges)
    return -1


class TicTacToeGame(BaseGame):
    name        = "tictactoe"
    description = "Tic-tac-toe"
    min_players = 1
    max_players = 1

    def __init__(self) -> None:
        self._board:  list[str] = [" "] * 9
        self._player: str = ""
        self._over:   bool = False

    def start(self, players: list[str]) -> str:
        self._player = players[0]
        return (
            "Tic-tac-toe: You (X) vs Machine (O)\n"
            f"{self._render()}\n"
            "Your turn — enter a number 1-9"
        )

    def on_message(self, sender: str, text: str) -> list[tuple[str, str]]:
        text = text.strip()
        if text.lower() in ("quit", "q"):
            self._over = True
            return [(sender, "Game abandoned.")]

        if not text.isdigit() or not (1 <= int(text) <= 9):
            return [(sender, "Enter a number 1-9.")]

        idx = int(text) - 1
        if self._board[idx] != " ":
            return [(sender, "That square is taken. Choose another.")]

        # Player move
        self._board[idx] = "X"

        if self._check_winner() == "X":
            self._over = True
            return [(sender, f"{self._render()}\nYou win!")]

        if " " not in self._board:
            self._over = True
            return [(sender, f"{self._render()}\nDraw!")]

        # AI move
        ai = _ai_move(self._board)
        self._board[ai] = "O"

        if self._check_winner() == "O":
            self._over = True
            return [(sender, f"{self._render()}\nMachine wins!")]

        if " " not in self._board:
            self._over = True
            return [(sender, f"{self._render()}\nDraw!")]

        return [(sender, f"{self._render()}\nYour turn (X) — enter 1-9")]

    @property
    def is_over(self) -> bool:
        return self._over

    def _render(self) -> str:
        b = self._board
        def cell(i): return b[i] if b[i] != " " else str(i + 1)
        return (
            f" {cell(0)} │ {cell(1)} │ {cell(2)} \n"
            f"───┼───┼───\n"
            f" {cell(3)} │ {cell(4)} │ {cell(5)} \n"
            f"───┼───┼───\n"
            f" {cell(6)} │ {cell(7)} │ {cell(8)} "
        )

    def _check_winner(self) -> str | None:
        for a, b, c in _WINS:
            if self._board[a] != " " and self._board[a] == self._board[b] == self._board[c]:
                return self._board[a]
        return None
