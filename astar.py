'''
Copyright (c) 2013 Gregory Burlet

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
'''

from astarguitar.score.score import Score
from astarguitar.score.scoreevent import Note, Chord
from astarguitar.guitar.guitarevent import Pluck, Strum
from astarguitar.guitar.guitar import Guitar
import networkx as nx
from pymei import XmlImport, XmlExport

import itertools

class ArrangeTabAstar(object):
    '''
    AStar class that forms a graph from a music score
    '''

    def __init__(self, score, guitar):
        self.score = score
        self.guitar = guitar
        self.graph = None

    def gen_tab(self, output_path=None):
        self.graph = self._gen_graph()

        # run the A* algorithm
        path = nx.astar_path(self.graph, 1, self.graph.number_of_nodes())
        # remove start and end nodes
        del path[0], path[-1]

        for n in path:
            n = self.graph.node[n]
            guitar_event = n['guitar_event']
            score_event = n['score_event']

            plucks = []
            if isinstance(guitar_event, Pluck):
                plucks.append((score_event.id, guitar_event))
            else:
                for p, n in zip(guitar_event.plucks, score_event.notes):
                    plucks.append((n.id, p))

            # add the tablature data to the original mei document
            for p in plucks:
                note = self.score.meidoc.getElementById(p[0])                
                note.addAttribute('tab.string', str(p[1].string+1))
                note.addAttribute('tab.fret', str(p[1].fret))

        if output_path is not None:
            # write the modified document to disk
            XmlExport.meiDocumentToFile(self.score.meidoc, output_path)
        else:
            # return a string of the MeiDocument
            return XmlExport.meiDocumentToText(self.score.meidoc)

    def _gen_graph(self):
        dg = nx.DiGraph()

        # start node for the search agent
        dg.add_node(1, guitar_event='start')

        prev_node_layer = [1]
        node_num = 2
        for e in self.score.score_events:
            # generate all possible fretboard combinations for this event
            candidates = self._get_candidates(e)

            node_layer = []
            for c in candidates:
                # each candidate position becomes a node on the graph
                dg.add_node(node_num, guitar_event=c, score_event=e)
                node_layer.append(node_num)

                # form edges between this node and nodes in previous layer
                edges = []
                for prev_node in prev_node_layer:
                    # calculate edge weight
                    w = ArrangeTabAstar.biomechanical_burlet(dg.node[prev_node]['guitar_event'], dg.node[node_num]['guitar_event'])
                    edges.append((prev_node, node_num, w))
                dg.add_weighted_edges_from(edges)

                node_num += 1

            prev_node_layer = node_layer

        # end node for the search agent
        dg.add_node(node_num, guitar_event='end')
        edges = [(prev_node, node_num, 0) for prev_node in prev_node_layer]
        dg.add_weighted_edges_from(edges)

        # debug: display draph
        # import matplotlib.pyplot as plt
        # nx.draw_networkx(dg)
        # plt.show()
        # print dg.nodes(data=True)

        return dg
    
    @staticmethod
    def biomechanical_burlet(n1, n2):
        '''
        Evaluate the biomechanical cost of moving from one node to another.

        PARAMETERS
        ----------
        n1: GuitarEvent
        n2: following GuitarEvent
        '''        

        distance = 0            # biomechanical distance
        w_distance = 2          # distance weight

        if n1 != 'start':
            # calculate distance between nodes
            if not n1.is_open():
                distance = n1.distance(n2)

        fret_penalty = 0
        w_fret_penalty = 1      # fret penalty weight
        fret_threshold = 7      # start incurring penalties above fret 7

        chord_distance = 0
        w_chord_distance = 2

        chord_string_distance = 0       # penalty for holes between string strums
        w_chord_string_distance = 1

        if isinstance(n2, Pluck):
            if n2.fret > fret_threshold:
                fret_penalty += 1
        else:
            frets = [p.fret for p in n2.plucks]
            if max(frets) > fret_threshold:
                fret_penalty += 1

            chord_distance = max(frets) - min(frets)

            strings = sorted([p.string for p in n2.plucks])
            for i in range(len(strings)-1,-1,-1):
                if i-1 < 0:
                    break
                s2 = strings[i]
                s1 = strings[i-1]
                chord_string_distance += (s2-s1)
                
            chord_string_distance -= len(strings)-1
        
        return w_distance*distance + w_fret_penalty*fret_penalty + w_chord_distance*chord_distance + w_chord_string_distance*chord_string_distance

    def _get_candidates(self, score_event):
        '''
        Calculate guitar pluck or strum candidates for a given note or chord event
        '''

        candidates = []

        if isinstance(score_event, Note):
            candidates = self.guitar.get_candidate_frets(score_event)
        elif isinstance(score_event, Chord):
            plucks = [self.guitar.get_candidate_frets(n) for n in score_event.notes]

            # get all combinations of plucks
            pluck_combinations = list(itertools.product(*plucks))

            # filter combinations to those that are valid strums
            # i.e., ensure plucks are not on the same string
            for c in pluck_combinations:
                active_strings = [p.string for p in c]
                if len(active_strings) == len(set(active_strings)):
                    # this combination of notes is good
                    # convert back to internal data format (Strum)
                    candidates.append(Strum(c))

        return candidates

def get_guitar_model(mei_path):
    '''
    Helper function to form the guitar model from 
    the mei file being parsed.
    '''

    # get guitar parameters
    mei_doc = XmlImport.documentFromFile(mei_path)
    
    staff_def = mei_doc.getElementsByName('staffDef')[0]
    strings = staff_def.getAttribute('tab.strings').value.split(' ')
    # bring tunings down from written octave to sounding octave
    strings = [s[:-1] + str(int(s[-1]) - 1) for s in strings]
    tuning = ' '.join(strings)

    if staff_def.hasAttribute('tab.capo'):
        capo = int(staff_def.getAttribute('tab.capo').value)
    else:
        capo = 0

    num_frets = 24

    g = Guitar(num_frets, tuning, capo)

    return g

if __name__ == '__main__':
    mei_path = '/Users/gburlet/University/MA/publications/ISMIR2013/robotaba/astarexample_input.mei'
    output_path = '/Users/gburlet/University/MA/publications/ISMIR2013/robotaba/astarexample_output.mei'

    guitar = get_guitar_model(mei_path)
    
    # generate the score model
    score = Score()
    score.parse_mei_file(mei_path)

    astar = ArrangeTabAstar(score, guitar)
    astar.gen_tab(output_path)
