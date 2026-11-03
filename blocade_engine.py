"""Pure, authoritative 2/4-player race-and-wall rules. No wallet or network access."""
from collections import deque
import random
from poker_engine import RuleError

SIZE = 9
STARTS = ((8, 4), (4, 0), (0, 4), (4, 8))


def new(players):
    sides = (0, 2) if len(players) == 2 else (0, 1, 2, 3)
    return dict(players=[dict(**p, side=side, pos=list(STARTS[side]),
                              walls=10 if len(players) == 2 else 5, out=False, misses=0)
                         for p, side in zip(players, sides)], walls=[], turn=0, ply=0,
                winner=None, last=None)


def goal(player, pos):
    row, col = pos
    return (row == 0, col == 8, row == 8, col == 0)[player['side']]


def blocked(walls):
    edges = set()
    for axis, row, col in walls:
        pairs = [((row, col+i), (row+1, col+i)) for i in (0, 1)] if axis == 'h' else [
            ((row+i, col), (row+i, col+1)) for i in (0, 1)]
        for a, b in pairs:
            edges.add((a, b)); edges.add((b, a))
    return edges


def neighbors(pos, edges):
    row, col = pos
    for other in ((row-1, col), (row+1, col), (row, col-1), (row, col+1)):
        if all(0 <= n < SIZE for n in other) and (tuple(pos), other) not in edges:
            yield other


def distance(player, edges, pos=None):
    origin = tuple(player['pos'] if pos is None else pos)
    queue = deque([(origin, 0)]); seen = {origin}
    while queue:
        here, steps = queue.popleft()
        if goal(player, here): return steps
        for nxt in neighbors(here, edges):
            if nxt not in seen:
                seen.add(nxt); queue.append((nxt, steps+1))
    return 999


def moves(state, index=None):
    index = state['turn'] if index is None else index
    player = state['players'][index]
    if player['out']: return []
    origin = tuple(player['pos']); edges = blocked(state['walls'])
    occupied = {tuple(p['pos']) for i, p in enumerate(state['players']) if i != index and not p['out']}
    result = set()
    for nxt in neighbors(origin, edges):
        if nxt not in occupied:
            result.add(nxt); continue
        direction = (nxt[0]-origin[0], nxt[1]-origin[1])
        beyond = (nxt[0]+direction[0], nxt[1]+direction[1])
        options = set(neighbors(nxt, edges))
        if beyond in options and beyond not in occupied:
            result.add(beyond)
        else:
            # A pawn, boundary or wall behind the adjacent pawn permits side jumps.
            for side in options:
                delta = (side[0]-nxt[0], side[1]-nxt[1])
                if delta[0]*direction[0]+delta[1]*direction[1] == 0 and side not in occupied:
                    result.add(side)
    return [list(p) for p in sorted(result)]


def wall_shape_valid(walls, wall):
    axis, row, col = wall
    if axis not in ('h', 'v') or any(type(n) is not int or not 0 <= n < 8 for n in (row, col)):
        return False
    for a, r, c in walls:
        if (r, c) == (row, col): return False  # crossing or identical
        if a == axis and ((axis == 'h' and r == row and abs(c-col) < 2) or
                          (axis == 'v' and c == col and abs(r-row) < 2)):
            return False
    return True


def wall_valid(state, wall):
    if not wall_shape_valid(state['walls'], wall): return False
    edges = blocked([*state['walls'], wall])
    return all(p['out'] or distance(p, edges) < 999 for p in state['players'])


def advance(state):
    state['ply'] += 1
    if state['winner'] is not None: return
    for step in range(1, len(state['players'])+1):
        nxt = (state['turn']+step) % len(state['players'])
        if not state['players'][nxt]['out']:
            state['turn'] = nxt; return


def act(state, action):
    player = state['players'][state['turn']]
    if state['winner'] is not None or player['out']: raise RuleError('這局已結束。')
    kind = action.get('kind')
    if kind == 'move':
        pos = action.get('pos')
        if not isinstance(pos, list) or len(pos) != 2 or any(type(n) is not int for n in pos) or pos not in moves(state):
            raise RuleError('這個位置不能走，請選擇亮起的格子。')
        player['pos'] = pos[:]
        if goal(player, pos): state['winner'] = state['turn']
    elif kind == 'wall':
        wall = action.get('wall')
        if not player['walls']: raise RuleError('牆壁已用完，請移動棋子。')
        if not isinstance(wall, list) or len(wall) != 3 or not wall_valid(state, wall):
            raise RuleError('牆壁不能重疊、交叉或封死任何人的終點路線。')
        state['walls'].append(wall[:]); player['walls'] -= 1
    elif kind == 'wait' and not moves(state):
        pass  # Four pawns can temporarily occupy every available landing square.
    else:
        raise RuleError('請選擇走棋或放牆。')
    state['last'] = dict(player=state['turn'], **action)
    advance(state)


def resign(state, index):
    player = state['players'][index]
    if player['out'] or state['winner'] is not None: return
    player['out'] = True
    remaining = [i for i, p in enumerate(state['players']) if not p['out']]
    if len(remaining) == 1: state['winner'] = remaining[0]
    state['last'] = dict(player=index, kind='resign')
    if index == state['turn']: advance(state)
    else: state['ply'] += 1


def choose(state, *, walls=True):
    """Bounded one-ply shortest-path search; same legal actions as a human."""
    index = state['turn']; player = state['players'][index]
    edges = blocked(state['walls']); legal = moves(state)
    if not legal:
        return dict(kind='wait')
    best_pos = min(legal, key=lambda pos: distance(player, edges, pos))
    move = dict(kind='move', pos=best_pos)
    if goal(player, best_pos) or not walls or not player['walls']: return move
    rivals = [p for i, p in enumerate(state['players']) if i != index and not p['out']]
    own = distance(player, edges); nearest = min(distance(p, edges) for p in rivals)
    best_score = nearest-distance(player, edges, best_pos)
    # A wall spends a finite resource: require a meaningful gain over moving.
    best = move
    candidates = [('h', r, c) for r in range(8) for c in range(8)] + [('v', r, c) for r in range(8) for c in range(8)]
    random.shuffle(candidates)
    for wall in candidates:
        if not wall_shape_valid(state['walls'], wall): continue
        after = blocked([*state['walls'], wall])
        graph = [[] for _ in range(81)]
        for r in range(9):
            for c in range(9):
                graph[r*9+c] = [rr*9+cc for rr,cc in neighbors((r,c), after)]
        def length(p):
            origin = p['pos'][0]*9+p['pos'][1]
            queue = deque([(origin,0)]); seen = {origin}; side = p['side']
            while queue:
                cell, steps = queue.popleft()
                if (cell < 9, cell%9 == 8, cell >= 72, cell%9 == 0)[side]: return steps
                for nxt in graph[cell]:
                    if nxt not in seen: seen.add(nxt); queue.append((nxt,steps+1))
            return 999
        lengths = {p['uid']:length(p) for p in state['players'] if not p['out']}
        if max(lengths.values()) >= 999: continue
        mine = lengths[player['uid']]
        other = min(lengths[p['uid']] for p in rivals)
        score = other-mine-.35
        if score > best_score and (other > nearest or mine < own):
            best_score = score; best = dict(kind='wall', wall=list(wall))
    return best
