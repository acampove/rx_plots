'''
Script used to compare variables in the same dataframe 
'''
# pylint: disable=no-name-in-module, logging-fstring-interpolation, line-too-long

import os
import glob
import pprint
import argparse
from importlib.resources import files
from dataclasses         import dataclass

import yaml
import mplhep
import dmu.generic.utilities as gut
from ROOT                    import RDataFrame, EnableImplicitMT
from dmu.plotting.plotter_1d import Plotter1D
from dmu.logging.log_store   import LogStore
from rx_data.rdf_getter      import RDFGetter
from rx_selection            import selection as sel

log=LogStore.add_logger('rx_selection:compare')
# ---------------------------------
@dataclass
class Data:
    '''
    Class used to share attributes
    '''
    nthreads   = 13
    trigger_mm = 'Hlt2RD_BuToKpMuMu_MVA'
    trigger_ee = 'Hlt2RD_BuToKpEE_MVA'
    d_reso     = {'jpsi' : 'B_const_mass_M', 'psi2' : 'B_const_mass_psi2S_M'}
    data_dir   = os.environ['DATADIR']
    l_kind     = ['resolution']

    mplhep.style.use('LHCb2')

    q2_bin  : str
    sample  : str
    trigger : str
    config  : str
    substr  : str
    brem    : int

    chanel  : str
    cfg_dir : str

    l_col  = []
# ---------------------------------
def _initialize() -> None:
    if Data.nthreads > 1:
        EnableImplicitMT(Data.nthreads)

    cfg_dir = files('rx_plotter_data').joinpath('compare')

    Data.cfg_dir = cfg_dir
    log.info(f'Picking configuration from: {Data.cfg_dir}')

    l_yaml  = glob.glob(f'{Data.data_dir}/samples/*.yaml')

    d_sample= { os.path.basename(path).replace('.yaml', '') : path for path in l_yaml }
    log.info('Using paths:')
    pprint.pprint(d_sample)
    RDFGetter.samples = d_sample
# ---------------------------------
def _apply_definitions(rdf : RDataFrame, cfg : dict) -> RDataFrame:
    if 'definitions' not in cfg:
        return rdf

    d_def = cfg['definitions']
    for name, expr in d_def.items():
        rdf = rdf.Define(name, expr)

    return rdf
# ---------------------------------
def _check_entries(rdf : RDataFrame) -> None:
    nentries = rdf.Count().GetValue()

    if nentries > 0:
        return

    rep = rdf.Report()
    rep.Print()

    raise ValueError('Found zero entries in dataframe')
# ---------------------------------
def _filter_by_brem(rdf : RDataFrame) -> RDataFrame:
    if Data.brem is None:
        return rdf

    brem_cut = f'nbrem == {Data.brem}' if Data.brem in [0, 1] else f'nbrem >= {Data.brem}'
    rdf = rdf.Filter(brem_cut, 'nbrem')

    return rdf
# ---------------------------------
@gut.timeit
def _get_rdf() -> RDataFrame:
    cfg = _get_cfg()
    gtr = RDFGetter(sample=Data.sample, trigger=Data.trigger)
    rdf = gtr.get_rdf()
    rdf = _apply_definitions(rdf, cfg)

    analysis = 'EE' if Data.trigger == Data.trigger_ee else 'MM'
    d_sel = sel.selection(project='RK', analysis=analysis, q2bin=Data.q2_bin, process=Data.sample)

    if 'selection' in cfg:
        d_cut = cfg['selection']
        d_sel.update(d_cut)

    for cut_name, cut_value in d_sel.items():
        log.info(f'{cut_name:<20}{cut_value}')
        rdf = rdf.Filter(cut_value, cut_name)

    rdf = _filter_by_brem(rdf)

    return rdf
# ---------------------------------
def _parse_args() -> None:
    parser = argparse.ArgumentParser(description='Script used to make comparison plots between distributions in the same dataframe')
    parser.add_argument('-q', '--q2bin'  , type=str, help='q2 bin' , choices=['low', 'central', 'jpsi', 'psi2', 'high'], required=True)
    parser.add_argument('-s', '--sample' , type=str, help='Sample' , required=True)
    parser.add_argument('-t', '--trigger', type=str, help='Trigger' , required=True, choices=[Data.trigger_mm, Data.trigger_ee])
    parser.add_argument('-c', '--config' , type=str, help='Configuration', required=True, choices=Data.l_kind)
    parser.add_argument('-x', '--substr' , type=str, help='Substring that must be contained in path, e.g. magup')
    parser.add_argument('-b', '--brem'   , type=int, help='Brem category', choices=[0, 1, 2])
    args = parser.parse_args()

    Data.q2_bin = args.q2bin
    Data.sample = args.sample
    Data.trigger= args.trigger
    Data.config = args.config
    Data.substr = args.substr
    Data.brem   = args.brem
# ---------------------------------
def _get_cfg() -> dict:
    cfg_path= f'{Data.cfg_dir}/{Data.config}.yaml'
    cfg_path= str(cfg_path)

    with open(cfg_path, encoding='utf=8') as ifile:
        cfg = yaml.safe_load(ifile)

    plt_dir = cfg['saving']['plt_dir']
    cfg['saving']['plt_dir'] = _get_out_dir(plt_dir)

    for d_setting in cfg['plots'].values():
        d_setting['title'] = f'Brem {Data.brem}; {Data.sample}'

    return cfg
# ---------------------------------
def _get_out_dir(plt_dir : str) -> str:
    if Data.brem is None:
        brem_name = 'all'
    else:
        brem_name = f'{Data.brem:03}'

    sample  = Data.sample.replace('*', 'p')
    out_dir = f'{plt_dir}/{sample}/{Data.trigger}/{Data.q2_bin}/{brem_name}'
    if Data.substr is not None:
        out_dir = f'{out_dir}/{Data.substr}'

    return out_dir
# ---------------------------------
def _rdf_from_def(rdf : RDataFrame, d_def : dict) -> RDataFrame:
    d_var = d_def['vars']
    for name, expr in d_var.items():
        rdf = rdf.Define(name, expr)

    if 'cuts' not in d_def:
        return rdf

    d_cut = d_def['cuts']
    for cut_name, cut_expr in d_cut.items():
        rdf = rdf.Filter(cut_expr, cut_name)

    return rdf
# ---------------------------------
def _get_inp() -> dict[str,RDataFrame]:
    cfg    = _get_cfg()
    rdf_in = _get_rdf()

    d_cmp = cfg['comparison']
    d_rdf = {}
    for kind, d_def in d_cmp.items():
        rdf = _rdf_from_def(rdf_in, d_def)
        _check_entries(rdf)
        d_rdf[kind] = rdf

    return d_rdf
# ---------------------------------
def _plot(d_rdf : dict[str,RDataFrame]) -> None:
    cfg= _get_cfg()
    del cfg['definitions']

    ptr=Plotter1D(d_rdf=d_rdf, cfg=cfg)
    ptr.run()
# ---------------------------------
def main():
    '''
    Script starts here
    '''
    _parse_args()
    _initialize()

    d_rdf = _get_inp()
    _plot(d_rdf)
# ---------------------------------
if __name__ == 'main':
    main()
