from __future__ import division
import numpy as np
import networkx as nx
from collections import defaultdict
import hashlib
import os
import cPickle as pickle
from cStringIO import StringIO

from transvizutil import rgb2hexa, num_args, get_usages, normalize_transmat

# TODO add igraph kk layout
# TODO circo bend through middle?
# TODO node shrinking by adding node copies behind the originals!

# default graphviz attributes

graphdefaults = dict(
    dpi='72',
    outputorder='edgesfirst',
    # bgcolor='transparent',
    # splines='true',  # segfault? https://github.com/ellson/graphviz/issues/42
)

nodedefaults = dict(
    shape='circle',
    fillcolor='white',
    style='filled',
    fixedsize='true',
)

edgedefaults = dict()

# default arguments to graphviz layout routines

graphviz_layouts = {
    'twopi':{},
    'gvcolor':{},
    'wc':{},
    'ccomps':{},
    'tred':{},
    'sccmap':{},
    'fdp':{},
    'circo':{},
    'neato':{'overlap':'false','sep':'+8'},
    'acyclic':{},
    'nop':{},
    'gvpr':{},
    'dot':{},
    'sfdp':{},
}

# default arguments to networkx layout routines

networkx_layouts = {
    'circular':{'scale':120},
    'shell':{'scale':120},
    'spring':{'scale':120},
    'spectral':{'scale':250},
    'fruchterman_reingold':{'scale':120},
}


# converters from my attribute formats to graphviz formats

converters = defaultdict(
    lambda: str,
    {
        'pos': lambda xy: '%f,%f!' % xy,
        'color': lambda rgba: rgb2hexa(rgba),
        'fillcolor': lambda rgba: rgb2hexa(rgba),
        'weight': lambda x: x,
    }
)


def convert(dct):
    ret = {}
    for attr, val in dct.items():
        try:
            ret[attr] = converters[attr](val)
        except:
            ret[attr] = val
    return ret


class TransGraph(nx.DiGraph):
    def __init__(self,A,norm=None):
        self.A = A
        self.usages = get_usages(A)

        if norm == 'row':
            self.A = normalize_transmat(A)
        elif norm == 'max':
            self.A = self.A / self.A.max()
        else:
            assert norm is None

        # initialize as a nx.DiGraph
        super(TransGraph,self).__init__(A)

        # set defaults
        self.graph['graph'] = graphdefaults
        self.graph['node'] = nodedefaults
        self.graph['edge'] = edgedefaults

    def graph_attrs(self,**kwargs):
        self.graph['graph'].update(convert(kwargs))
        return self

    def node_attrs(self,func,selector=lambda dct: True):
        nargs = num_args(func)

        if nargs == 1:
            for i, node in self.nodes_iter(data=True):
                node.update(convert(func(i)))
        elif nargs == 2:
            for i, node in self.nodes_iter(data=True):
                node.update(convert(func(i,self.usages[i])))
        else:
            raise ValueError('func must take 1 or 2 arguments')

        return self

    def edge_attrs(self,func,selector=lambda dct: True):
        nargs = num_args(func)

        if nargs == 1:
            for i, j, edge in self.edges_iter(data=True):
                edge.update(convert(func((i,j))))
        elif nargs == 2:
            for i, j, edge in self.edges_iter(data=True):
                edge.update(convert(func(i,j)))
        elif nargs == 3:
            for i, j, edge in self.edges_iter(data=True):
                edge.update(convert(func(i,j,self.A[i,j])))
        else:
            raise ValueError('func must take 1, 2, or 3 arguments')

        return self

    @staticmethod
    def get_cachename(algname,weights):
        return algname + hashlib.sha1(np.array(weights)).hexdigest()[:6]

    def layout(self,algname=None,posdict=None,**kwargs):
        assert (algname is not None) ^ (posdict is not None), \
            'must pass algname or posdict'

        if posdict is None:
            cachename = self.get_cachename(
                algname, [self.edge[i][j]['weight'] for (i,j) in self.edges()])

            if os.path.isfile(cachename):
                with open(cachename,'r') as infile:
                    posdict = pickle.load(infile)
            else:
                if algname in graphviz_layouts:
                    self.graph['graph'].update(dict(graphviz_layouts[algname],**kwargs))
                    posdict = nx.graphviz_layout(self,algname)
                elif algname in networkx_layouts:
                    func = nx.__dict__[algname+'_layout']
                    kwargs = dict(networkx_layouts[algname],**kwargs)
                    kwargs['scale'] *= np.sqrt(self.order())
                    posdict = func(self,**kwargs)
                else:
                    raise ValueError(
                        'algname must be one of %s' %
                        (graphviz_layouts.keys() + networkx_layouts.keys()))

                with open(cachename,'w') as outfile:
                    pickle.dump(posdict,outfile,protocol=-1)

        self.node_attrs(lambda i: {'pos':posdict[i]})
        self.posdict = posdict
        self.has_layout = True

        return self

    def draw(self,outfile=None,matplotlib=True,notebook=False):
        agraph = nx.to_agraph(self)
        agraph.has_layout = self.has_layout

        if outfile is None:
            pngstr = self._get_agraph_pngstr(agraph)

            if matplotlib and not notebook:
                import matplotlib.pyplot as plt
                import matplotlib.image as mpimg
                plt.imshow(mpimg.imread(pngstr),aspect='equal')
                plt.axis('off')

            if notebook:
                from IPython.display import Image, display
                display(Image(data=pngstr))
        else:
            agraph.draw(outfile)

    @staticmethod
    def _get_agraph_pngstr(agraph):
        sio = StringIO()
        agraph.draw(sio,format='png')
        ret = sio.getvalue()
        sio.close()
        return ret

    def prune_edges(self,func):
        nargs = num_args(func)

        if nargs == 1:
            to_remove = \
                [(i,j) for i, j, edge in self.edges_iter(data=True)
                 if func((i,j))]
        elif nargs == 2:
            to_remove = \
                [(i,j) for i, j, edge in self.edges_iter(data=True)
                 if func(i,j)]
        elif nargs == 3:
            to_remove = \
                [(i,j) for i, j, edge in self.edges_iter(data=True)
                 if func(i,j,self.A[i,j])]
        else:
            raise ValueError('func must take 1, 2, or 3 arguments')

        for e in to_remove:
            self.remove_edge(*e)

        return self

    ### convenience

    def highlight(self,node,
            incolor=(0.21568627450980393, 0.47058823529411764, 0.7490196078431373),
            outcolor=(0.996078431372549, 0.7019607843137254, 0.03137254901960784)):
        self.node_attrs(
            lambda i: {'color': (0.,0.,0.,1.0 if i == node else 0.05)})\
            .edge_attrs(
            lambda i,j,aij:
                {'color': (incolor if j == node else outcolor)
                    + (aij if i == node or j == node else 0.0,)})
        return self


class TransDiff(TransGraph):
    def __init__(self,(A,B),norm=None):
        self.A = A
        self.B = B

        self.A_usages = get_usages(A)
        self.B_usages = get_usages(B)

        if norm == 'row':
            self.A = normalize_transmat(A)
            self.B = normalize_transmat(B)
        elif norm == 'max':
            self.A = self.A / self.A.max()
            self.B = self.B / self.B.max()
        elif norm == 'difference':
            val = np.abs(self.B - self.A).max()
            self.A = self.A / val
            self.B = self.B / val
        else:
            assert norm is None

        self.has_foreground_nodes = False

        # initialize as a nx.DiGraph
        super(TransGraph,self).__init__(A+B)

        # set defaults
        self.graph['graph'] = graphdefaults
        self.graph['node'] = nodedefaults
        self.graph['edge'] = edgedefaults

    def edge_attrs(self,func):
        nargs = num_args(func)

        if nargs == 1:
            for i, j, edge in self.edges_iter(data=True):
                edge.update(convert(func((i,j))))
        elif nargs == 2:
            for i, j, edge in self.edges_iter(data=True):
                edge.update(convert(func(i,j)))
        elif nargs == 4:
            for i, j, edge in self.edges_iter(data=True):
                edge.update(convert(func(i,j,self.A[i,j],self.B[i,j])))
        else:
            raise ValueError('func must take 1, 2, or 4 arguments')

        return self

    def node_attrs(self,func,selector=lambda dct: 'backgroundnode' not in dct):
        nargs = num_args(func)

        if nargs == 1:
            for i, node in self.nodes_iter(data=True):
                if selector(node):
                    node.update(convert(func(i)))
        elif nargs == 3:
            for i, node in self.nodes_iter(data=True):
                if selector(node):
                    node.update(convert(func(i,self.A_usages[i],self.B_usages[i])))
        else:
            raise ValueError('func must take 1 or 3 arguments')

        return self

    def prune_edges(self,func,selector=lambda dct: True):
        nargs = num_args(func)

        if nargs == 1:
            to_remove = \
                [(i,j) for i, j, edge in self.edges_iter(data=True)
                 if func((i,j))]
        elif nargs == 2:
            to_remove = \
                [(i,j) for i, j, edge in self.edges_iter(data=True)
                 if func(i,j)]
        elif nargs == 4:
            to_remove = \
                [(i,j) for i, j, edge in self.edges_iter(data=True)
                 if func(i,j,self.A[i,j],self.B[i,j])]
        else:
            raise ValueError('func must take 1, 2, or 4 arguments')

        for e in to_remove:
            self.remove_edge(*e)

        return self

    def foreground_node_attrs(self,func,selector=lambda x: True):
        if not self.has_foreground_nodes:
            for i, node in self.nodes_iter(data=True):
                self.add_node("%d'" % i, dict(foregroundnode=True,label=i,**node))
            self.has_foreground_nodes = True

        nargs = num_args(func)

        if nargs == 1:
            for i, node in self.nodes_iter(data=True):
                if 'foregroundnode' in node and selector(node):
                    i = int(i[:-1])
                    node.update(convert(func(i)))
        elif nargs == 3:
            for i, node in self.nodes_iter(data=True):
                if 'foregroundnode' in node and selector(node):
                    i = int(i[:-1])
                    node.update(convert(func(i,self.A_usages[i],self.B_usages[i])))
        else:
            raise ValueError('func must take 1 or 3 arguments')

        return self

    # TODO change the ordering in the dot file?

    # def layout(self,algname=None,posdict=None,**kwargs):
    #     super(TransDiff,self).layout(algname=algname,posdict=posdict,**kwargs)
    #     if self.has_background_nodes:
    #         # TODO
    #         raise NotImplementedError('call layout before adding bgnd nodes')

    # def draw(self,outfile=None,matplotlib=True,notebook=False):
    #     # TODO put background nodes at the start of the file so they are drawn
    #     # first
    #     raise NotImplementedError

