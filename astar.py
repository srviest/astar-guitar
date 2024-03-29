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

import os
from score.score import Score
from score.scoreevent import Note, Chord
from guitar.guitarevent import Pluck, Strum
from guitar.guitar import Guitar
import networkx as nx
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

        strums = []
        for n in path:
            n = self.graph.node[n]
            guitar_event = n['guitar_event']
            score_event = n['score_event']

            plucks = []
            if isinstance(guitar_event, Pluck):
                plucks.append((score_event.id, guitar_event))
            else:
                for pluck, note in zip(guitar_event.plucks, score_event.notes):
                    plucks.append((note.id, pluck))
            strums.append(plucks)

        # figure out of this is an MEI or a MusicXML file
        ext = os.path.splitext(output_path)[-1]
        if ext == ".mei":
            from pymei import XmlExport

            # add the tablature data to the original mei document
            for s in strums:
                for p in s:
                    note = self.score.doc.getElementById(p[0])                
                    note.addAttribute('tab.string', str(p[1].string+1))
                    note.addAttribute('tab.fret', str(p[1].fret))

            if output_path is not None:
                # write the modified document to disk
                XmlExport.meiDocumentToFile(self.score.mei, output_path)
            else:
                # return a string of the MeiDocument
                return XmlExport.meiDocumentToText(self.score.mei)
        elif ext == ".xml":
            from lxml import etree

            # add the tablature data to the original MusicXML document
            for s in strums:
                for p in s:
                    try:
                        note = self.score.doc.xpath("part/measure/note[@id='%s']" % p[0])[0]
                    except IndexError:
                        raise ValueError("Oh snap! We couldn't find note id=%s in the MusicXML document" % p[0])

                    # add string and fret information to note
                    notations = note.find("notations")
                    if notations is None:
                        notations = etree.SubElement(note, "notations")

                    technical = etree.SubElement(notations, "technical")
                    string = etree.SubElement(technical, "string")
                    string.text = str(p[1].string+1)
                    fret = etree.SubElement(technical, "fret")
                    fret.text = str(p[1].fret)

            # append staff-details so GuitarPro can read the string/fret data
            m1_attrs = self.score.doc.xpath("part/measure[@number='1']/attributes")[0]
            staff_details = etree.SubElement(m1_attrs, "staff-details")
            staff_lines = etree.SubElement(staff_details, "staff-lines")
            staff_lines.text = str(len(self.guitar.strings))
            for i, n in enumerate(reversed(self.guitar.strings)):
                staff_tuning = etree.SubElement(staff_details, "staff-tuning")
                staff_tuning.set("line", str(i+1))
                tuning_step = etree.SubElement(staff_tuning, "tuning-step")
                tuning_step.text = n.pname
                tuning_octave = etree.SubElement(staff_tuning, "tuning-octave")
                tuning_octave.text = str(n.oct)

            self.score.cleanup()

            if output_path is not None:
                # write the modified document to disk
                with open(output_path, 'w') as f:
                    self.score.doc.write(f)
            else:
                # return a string of the MusicXML document
                return etree.tostring(self.score.doc)

    def _gen_graph(self):
        dg = nx.DiGraph()

        # start node for the search agent
        dg.add_node(1, guitar_event='start')

        prev_node_layer = [1]
        node_num = 2
        num_nodes = len(self.score.score_events)
        for i, e in enumerate(self.score.score_events):
            # make sure chord has a polyphony <= 6
            if isinstance(e, Chord) and len(e.notes) > 6:
                e.notes = enotes[:6]

            # generate all possible fretboard combinations for this event
            candidates = self._get_candidates(e)
            if len(candidates) == 0:
                continue

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
                    frets = [p.fret for p in c if p.fret > 0]
                    if len(frets):
                        if max(frets) - min(frets) <= 7:
                            # this combination of notes is good
                            # convert back to internal data format (Strum)
                            candidates.append(Strum(c))
                    else:
                        candidates.append(Strum(c))

        return candidates

def get_guitar_model(mei_path):
    '''
    Helper function to form the guitar model from 
    the mei file being parsed.
    '''

    from pymei import XmlImport, XmlExport

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
