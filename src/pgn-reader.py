from io import StringIO
from sys import stdin, stderr
from multiprocessing import Process, Queue

import chess, chess.pgn

"""
Reads PGN data from stdin, extract the positions that are evaluated and 
outputs them to stdout, one by line, in the following format:
FEN;EVAL
where FEN is the complete FEN string of the position and EVAL is a signed integer in centipawns.
Ignores position that are evaluated with a mate score.
"""

# Number of parser threads
NUM_WORKERS = 6

# A leaner PGN visitor that only reads moves and comments, and skips everything 
# if it encounters an unevaluated game.
class FastGameBuilder(chess.pgn.GameBuilder):

    def begin_game(self):
        self.game = self.Game()
        self.variation_stack = [self.game]
        self.first = True

    def visit_comment(self, comment):
        self.variation_stack[0].comment = comment
        if self.first and self.variation_stack[0].eval() is None:
            raise Skip()
        self.first = False

    def visit_move(self, board: chess.Board, move: chess.Move):
        self.variation_stack[0] = self.variation_stack[0].add_variation(move=move)

    def handle_error(self, error):
        raise Skip()

    def begin_headers(self): pass
    def visit_header(self, tagname, tagvalue): pass
    def visit_nag(self, nag): pass
    def begin_variation(self): pass
    def end_variation(self): pass
    def visit_result(self, result): pass

# Inherits BaseException because Exceptions are swallowed by python-chess.
class Skip(BaseException):
    pass

def print_results(res_queue):
    # Keeps track of the number of position extracted.
    pos_count = 0
    bytes_count = 0
    update = 100

    while True:
        # Get the next results.
        batch = res_queue.get()

        # Outputs the results and update the stats.
        pos_count += len(batch)
        for res in batch:
            print(res)
            bytes_count += len(res)+1

        # Print the advancement of the task every 100 batches.
        if update == 100:
            update = 0
            print(f"Position count: {pos_count // 1000}K ({bytes_count / 1000000:.2f}MB)", end="\r", file=stderr)
        else:
            update += 1

# Reads PGN games from stdin and converts them into evaluated FEN positions.
def worker_main(in_queue, res_queue):
    # The chess board.
    board = chess.Board()

    while True:
        try:
            # Parse the next chunk.
            chunk = in_queue.get()
            game = chess.pgn.read_game(chunk, Visitor=FastGameBuilder)
            chunk.close()
        except Skip:
            continue

        if game is None:
            break

        # Reset the board to it's starting position.
        board.reset()
        batch = []

        # For each position in the game.
        while game := game.next():
            # Do the move
            board.push(game.move)

            if not (evaluation := game.eval()):
                continue

            white_eval = evaluation.white()
            if white_eval.is_mate():
                continue

            # Format it like: "<fen>;<eval>\n".
            batch.append(f"{board.fen()};{white_eval.score()}")

        res_queue.put(batch)

def main():
    # For threading purposes.
    in_queue = Queue(maxsize=8)
    res_queue = Queue(maxsize=8)

    # The process that prints results.
    Process(
        target=print_results,
        kwargs={
            "res_queue": res_queue,
        },
    ).start()

    # The processes that parse PGN games.
    for _ in range(NUM_WORKERS):
        Process(
            target=worker_main,
            daemon=True,
            kwargs={
                "in_queue": in_queue,
                "res_queue": res_queue,
            },
        ).start()

    # Reads lines from stdin until there is nothing left.
    lines = []
    after_headers = False

    for line in stdin:
        if line.isspace():
            if after_headers:
                in_queue.put(StringIO("".join(lines)))
                lines = []
                after_headers = False
            else:
                after_headers = True
        lines.append(line)

if __name__ == "__main__":
    main()