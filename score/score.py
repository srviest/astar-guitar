'''
Copyright (c) 2012 Gregory Burlet

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

from scoreevent import Note, Chord

pitch_names = ['C', 'D', 'E', 'F', 'G', 'A', 'B']

class Score(object):

    def __init__(self):
        '''
        Initialize a score 
        '''

        # musical events occuring in the input score
        self.score_events = []
        self.doc = None         # container for parsed music document

    def engrave(self):
        '''
        Call after self.score_events has been populated from file
        to print the internal data structure to the terminal.
        Mostly used for debugging.
        '''

        for e in self.score_events:
            print e

class MeiScore(Score):
    '''
    Initialize an MEI score
    '''

    def __init__(self):
        super(MeiScore, self).__init__()

    def parse_str(self, mei_str):
        '''
        Read an mei file from string and fill the score model
        '''

        from pymei import XmlImport
        self.doc = XmlImport.documentFromText(mei_str)
        self.parse_input()

    def parse_file(self, mei_path):
        '''
        Read an mei file and fill the score model
        '''

        from pymei import XmlImport
        self.doc = XmlImport.documentFromFile(str(mei_path))
        self.parse_input()

    def parse_input(self):
        '''
        Parse the score data into the internal data representation.
        '''
        
        measures = self.doc.getElementsByName('measure')
        for m in measures:
            # only parse first staff (instrument), the instrument to convert to tablature
            staff = m.getChildrenByName('staff')[0]
            # only parse first layer (assume only one voice)
            layer = staff.getChildrenByName('layer')[0]
            events = layer.getChildren()
            for e in events:
                if e.getName() == 'chord':
                    notes_in_chord = []
                    for n in e.getChildrenByName('note'):
                        note = self._handle_mei_note(n)    
                        notes_in_chord.append(note)
                    chord = Chord(notes_in_chord)
                    self.score_events.append(chord)
                elif e.getName() == 'note':
                    note = self._handle_mei_note(e)
                    self.score_events.append(note)

    def _handle_mei_note(self, note):
        '''
        Helper function that takes an mei note element
        and creates a Note object out of it.
        '''
        
        pname = note.getAttribute('pname').value
        # append accidental to pname for internal model
        if note.hasAttribute('accid.ges'):
            accid = note.getAttribute('accid.ges').value
            if accid == 'f':
                # convert to sharp
                pname = pitch_names[pitch_names.index(pname)-1 % len(pitch_names)] + '#'
            if accid == 's':
                pname += '#'
        oct = int(note.getAttribute('oct').value)
        id = note.getId()

        return Note(pname, oct, id)

class MusicXMLScore(Score):
    '''
    Initialize a MusicXML score
    '''

    def __init__(self):
        super(MusicXMLScore, self).__init__()

    def parse_str(self, xml_str):
        '''
        Read a MusicXML file from string and fill the score model
        '''

        from lxml import etree
        self.doc = etree.fromstring(xml_str)
        self.parse_input()

    def parse_file(self, xml_path):
        '''
        Read a MusicXML file and fill the score model
        '''

        from lxml import etree
        self.doc = etree.parse(xml_path)
        self.parse_input()

    def parse_input(self):
        '''
        Parse the score data into the internal data representation.
        '''

        def prune_notes(active_chord):
            '''
            Helper function that removes notes from the active chord
            that are not in their onset phase, i.e., this function prunes
            notes that are part of ties, etc.

            PARAMETERS:
            active_chord (list): list of note events

            RETURNS:
            score_event (scoreevent) a Note or a Chord depending on how much was pruned
            '''

            # discard active_notes that have ties = continue or stop
            for j in range(len(active_chord)-1,-1,-1):
                if active_chord[j]._tie_state == "continue" or active_chord[j]._tie_state == "stop":
                    del active_chord[j]

            score_event = None
            if len(active_chord) == 1:
                # one note remains, append to score events
                score_event = active_chord[0]
            elif len(active_chord) > 1:
                # more than one note remains, append chord to score events
                score_event = Chord(active_chord)
            
            return score_event

        notes = self.doc.findall("part/measure/note")
        active_notes = []
        for i, n in enumerate(notes):
            # append id to note elements so they can be retrieved later
            n.set("id", str(i+1))

            # skip rests
            if n.find("rest") is not None:
                continue

            note = self._handle_xml_note(n, str(i+1))
            active_notes.append(note)

            if i+1 < len(notes):
                # look ahead to see if next note element is a member of a chord
                if notes[i+1].find("chord") is None:
                    # this is the last note in a chord or is a single note
                    score_event = prune_notes(active_notes)
                    if score_event:
                        self.score_events.append(score_event)
                        active_notes = []
                else:
                    # a chord starts or continues
                    continue
            else:
                # deal with note/chord at the end of the score
                score_event = prune_notes(active_notes)
                if score_event:
                    self.score_events.append(score_event)

    def _handle_xml_note(self, n, nid):
        '''
        Helper function that takes a MusicXML note element
        and creates a Note object out of it.

        PARAMETERS:
        n (lxml element): note in xml format
        nid (int): desired note id

        RETURNS:
        note (ScoreEvent.Note): note in internal note representation
        '''

        pname = n.findtext("pitch/step")
        octave = int(n.findtext("pitch/octave"))
        note = Note(pname, octave, nid)

        alter = n.findtext("pitch/alter")
        if alter:
            note = note + int(alter)

        ties = n.findall("tie")
        if len(ties):
            tie_types = [t.get("type") for t in ties]
            if len(ties) == 1:
                if "start" in tie_types:
                    # start tie
                    note._tie_state = "start"
                else:
                    # end tie (note dies)
                    note._tie_state = "stop"
            else:
                # continue tie
                note._tie_state = "continue"
        else:
            # no tie, note just ends after duration
            note._tie_state = None

        return note 
