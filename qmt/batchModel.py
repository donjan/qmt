# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from __future__ import absolute_import, division, print_function
import numpy as np
import os
import json
from six import itervalues
import qmt


class Model:
    def __init__(self, modelPath=None, load=True):
        '''Class for creating, loading, and manipulating a json file that 
           contains information about the model.

            Keyword arguments
            ----------
            modelPath : str, default None
            Path to the model json file. If initialized with None, should be set
            manually before loading/saving.

            load : bool, default True
            If True, the constructor attempts to load the model from the file at
            modelPath. If False, the model is initialized to an empty state.
        '''
        self.modelPath = modelPath
        if load and modelPath is not None:
            self.loadModel(False)
        else:
            self.modelDict = self.genEmptyModelDict()

    def genEmptyModelDict(self):
        '''Generate an empty modelDict (dictionary of dictionaries)
        '''
        modelDict = {}
        modelDict['geometricParams'] = {}  # Geometric parameters for FreeCAD
        modelDict['3DParts'] = {}  # Information about the 3D parts of our model 
        modelDict['buildOrder'] = {} # The build order of the model
        modelDict['slices'] = {} # 2D slices that are used in physics processing.
        modelDict['materials'] = {}  # Information about the materials used in the structure
        # Information about the voltage sweep to execute
        modelDict['physicsSweep'] = {'type': 'sparse', 'sweepParts': {}, 'length': 1}
        modelDict['geomSweep'] = {}  # Information about the geometry sweep to execute
        modelDict['meshInfo'] = {} # Information about mesh refinement
        modelDict['comsolInfo'] = {'surfaceIntegrals': {}, 'volumeIntegrals': {},'zeroLevel':[None,None]}  # Information for COMSOL
        modelDict['jobSettings'] = {}  # Information on the job
        modelDict['pathSettings'] = {}  # Information on the paths to executables
        modelDict['postProcess'] = {'sweeps': {}, 'tasks': {}}
        return modelDict

    def genPhysicsSweep(self, partName, quantity, values, unit="", symbol=None, dense=False):
        """ Generate a parametric sweep and add it to modelDict.
        @param partName: name (str) of the solid whose property should be swept.
        @param quantity: name (str) of the quantity to be swept.
        @param values: list or numpy array with the values to sweep over
        @param unit: string with the unit of the parameter in a format recognizable by COMSOL.
        @param symbol: Variable name for the quantity used in the COMSOL model.
        @param dense: Whether to do a dense/filled sweep (True) or a sparse one (False).
        """
        sweep = {}
        sweep['part'] = partName
        sweep['quantity'] = quantity
        if symbol is None:
            symbol = quantity
        sweep['symbol'] = symbol
        sweep['values'] = list(values)
        sweep['unit'] = unit
        key = '{0}_{1}'.format(quantity, partName)  # This is how the parameters are build in comsol
        self.modelDict['physicsSweep']['length'] = len(list(values))
        self.modelDict['physicsSweep']['sweepParts'][key] = sweep
        # For now, only sparse sweeps are supported
        for part_name, part_info in self.modelDict['physicsSweep']['sweepParts'].items():
            assert len(part_info['values']) == len(list(values)), "Lengths of the different sweeps must match, only sparse sweeps supported."
        self.modelDict['physicsSweep']['type'] = 'dense' if dense else 'sparse'

    def genGeomSweep(self, param, vals, type='freeCAD'):
        """ Generate a parametric sweep and add it to modelDict. The units need to
        be whatever is accepted by FreeCAD.
        @param param: string with the name of the parameter to sweep over
        @param vals: list or numpy array with the values to sweep over
        @param type: type of geometric parameter. Legal values are "freeCAD", denoting
        parameters that are varied through FreeCAD spreadsheets, and "python", which
        are declared in build sequences in the run construction script.
        """
        sweep = {}
        sweep['vals'] = ', '.join(str(e) for e in vals)
        sweep['type'] = type
        self.modelDict['geomSweep'][param] = sweep

    def genSurfaceIntegral(self, partName, quantities=['V']):
        '''
        @param partName: string with the name of the part on which the surface integral
        should be performed
        @param quantities: list of strings with the quantities that should be
        integrated over. Default integral is over V
        '''
        self.modelDict['comsolInfo']['surfaceIntegrals'][partName] = quantities

    def genVolumeIntegral(self, partName, quantities=['V']):
        '''
        @param partName: string with the name of the part on which the surface integral
        should be performed
        @param quantities: list of strings with the quantities that should be
        integrated over. Default integral is over V
        '''
        self.modelDict['comsolInfo']['volumeIntegrals'][partName] = quantities

    def setSimZero(self,partName,property='workFunction'):
        ''' Sets the zero level for the electric potential in COMSOL simulations. This doesn't 
        impact any of the physics, but makes the results much easier to look at.
        @param partName: Target partName to use
        @param property: The property to use as the zero level.
        '''
        self.modelDict['comsolInfo']['zeroLevel'] = [partName,property]

    def genComsolInfo(self, meshExport=None, fileName='comsolModel', exportDir='solutions',
                      repairTolerance=None):
        '''
        Generate meta information required by COSMOL
        @param meshExport: string with name for the exported mesh. None means no mesh is exported
        @param repairTolerance: float with the repair tolerance for building the geometry in COMSOl
        @param fileName: string with the name of the resulting COMSOL file
        @param exportDir: string with directory to which results are exported
        '''
        self.modelDict['comsolInfo']['meshExport'] = meshExport
        self.modelDict['comsolInfo']['repairTolerance'] = repairTolerance
        self.modelDict['comsolInfo']['fileName'] = fileName
        self.modelDict['comsolInfo']['exportDir'] = exportDir


    def addPart(self,partName,fcName,directive,domainType,material=None,\
                z0=None,thickness=None,targetWire=None,shellVerts=None,depoZone=None,etchZone=None,\
                zMiddle=None,tIn=None,tOut=None,layerNum=None,lithoBase=[],\
                fillLitho=True,meshMaxSize=None,meshGrowthRate=None,boundaryCondition = None,\
                subtractList=[]):
        ''' Add a geometric part to the model. 
            @param partName: The descriptive name of this new part.
            @param fcName: The name of the 2D freeCAD object that this is built from.
            @param directive: The freeCAD directive is used to construct this part. 
                                Valid options for this are:
                                    extrude -- simple extrusion
                                    wire -- hexagonal nanowire about a polyline
                                    wireShell -- shell coating a specified nanowire
                                    SAG -- SAG structure
                                    lithography -- masked layer deposited on top
            @param material:    The material of the resulting part
            @param domainType: The type of domain this part represents:
                                Valid options are:
                                    semiconductor -- region permitted to self-consistently accumulate
                                    metalGate -- an electrode
                                    virtual -- a part just used for selection (ignores material)
                                    dielectric -- no charge accumulation allowed
            @param z0:          The starting z coordinate. Required for extrude, 
                                wire, SAG, and lithography directives.
            @param thickness:   The total thickness. Required for all
                                directives. On wireShell, this is interpreted
                                as the layer thickness.
            @param targetWire:  Target wire directive for a coating directive.
            @param shellVerts:  Vertices to use when rendering the coating. Required
                                for the shell directive.
            @param depoZone:    Sketch defining the (positive) mask for the deposition
                                of a wire coating. Note that only one of depoZone or
                                etchZone may be used
            @param etchZone:	Sketch defining the (negative) amsek for the depostion
            					of a wire coating. Note that only one of depoZone or
            					etchZone may be used.
            @param zMiddle:     The location for the "flare out" of the SAG directive.
            @param tIN:         The lateral distance from the 2D profile to the 
                                edge of the top bevel for the SAG directive.
            @param tOut:        The lateral distance from the 2D profile to the 
                                furtheset "flare out" location for the SAG directive.
            @param layerNum:    The layer (int) number used by the lithography directive.
                                Lower numbers go down first, with higher numbers 
                                deposited last.
            @param lithoBase:   The base partNames to use for the lithography directive.
                                For multi-step lithography, the bases are just all merged,
                                so there is no need to list this more than once.
            @param fillLitho:   Bool, defaulting to true. If set to false, will attempt
                                to hollow out lithography steps by subtracting the base
                                and subsequent lithography layers, but this can sometimes 
                                fail in opencascade. COMSOL takes care of this using 
                                parasolid if left to True.
            @param maxMeshSize: The maximum allowable mesh size for this part, in microns.
            @param meshGrowthRate: The maximum allowable mesh growth rate for this part
            @param boundaryCondition: One or more boundary conditions, if applicable, of the form of
                                a type -> value mapping. For example, this could be {'voltage':1.0}
                                or, more explicitly, {'voltage': {'type': 'dirichlet', 'value': 1.0,
                                                                  'unit': 'V'}}.
            @param subtractList: A list of partNames that should be subtracted from the
                                 current part when forming the final 3D objects. This
                                 subtraction is carried out in 3D using the COMSOL parasolid
                                 kernel or using shapely in 2D. 
        '''
        # First, run checks to make sure the input is valid:
        if partName in self.modelDict['3DParts']:
            raise NameError('Error - partName '+partName+' was duplicated!')
        if directive not in ['extrude','wire','wireShell','SAG','lithography']:
            raise NameError('Error - directive '+directive+' is not a valid directive!')
        if domainType not in ['semiconductor','metalGate','virtual','dielectric']:
            raise NameError('Error - domainType '+domainType+' not valid!')
        if (etchZone is not None) and (depoZone is not None):
            raise NameError('Error - etchZone and depoZone cannot both be set!')
        # Next, construct the dictionary entry:
        partDict = {}
        partDict['fileNames'] = {}
        partDict['fcName'] = fcName
        partDict['directive'] = directive
        partDict['material'] = material
        partDict['domainType'] = domainType
        partDict['z0'] = z0
        partDict['thickness'] = thickness
        partDict['targetWire'] = targetWire
        partDict['shellVerts'] = shellVerts
        partDict['depoZone'] = depoZone
        partDict['etchZone'] = etchZone
        partDict['zMiddle'] = zMiddle
        partDict['tIn'] = tIn
        partDict['tOut'] = tOut
        partDict['layerNum'] = layerNum
        partDict['lithoBase'] = lithoBase
        partDict['fillLitho'] = fillLitho
        partDict['meshMaxSize'] = meshMaxSize
        partDict['meshGrowthRate'] = meshGrowthRate
        partDict['boundaryCondition'] = boundaryCondition
        partDict['subtractList'] = subtractList
        self.modelDict['buildOrder'][len(self.modelDict['buildOrder'])] = partName
        self.modelDict['3DParts'][partName] = partDict

    def addCrossSection(self, sliceName, axis, distance):
        """
        Add a 2D cross section through the 3D model for postprocessing.

        @param sliceName: Name identifying the cross section.
        @param axis: 3D vector specifying the normal direction of the cross section plane.
        @param distance: Scalar distance of the cross section from the origin.
        """
        if sliceName in self.modelDict['slices']:
            raise RuntimeError("Error - sliceName", sliceName, "was duplicated!")
        info = {'sliceName': sliceName, 'crossSection': True, 'axis': axis, 'distance': distance}
        self.modelDict['slices'][sliceName] = {'sliceInfo': info}

    def registerCadPart(self, partName,fcName,fileName,reset=False):
        '''Register a 3D CAD part on disk that is associated with the freeCAD 3D part fcName.
        The idea here is that the partName knows what 3D entities were generated from it, what
        those parts are called on disk, and what they are called in the freeCAD file.
        '''
        if reset: # reset the file listing if we want to
            self.modelDict['3DParts'][partName]['fileNames']  = {} 
        self.modelDict['3DParts'][partName]['fileNames'][fcName] = fileName

    def genPart2D(self, partName, geometry, sliceName=None, material=None,
                  objType=None, domainType=None, boundaryConditions=None,
                  descriptors=None, bandOffset=None, surfaceChargeDensity=None,
                  bulkDoping=None, subtractList=None):
        '''Generate a 2D slice part and add it to the modelDict.
            
            sliceName: simulation slice that the part belongs to.

        '''
        twoDParts = self.modelDict['slices']
        # Establish the index of the current slice:
        if sliceName is None:
            sliceName = '0'
            if len(twoDParts) > 1 or len(twoDParts) == 1 and sliceName not in twoDParts:
                raise RuntimeError('sliceName cannot be unspecified if there are several slices')
        if sliceName not in twoDParts:
            twoDParts[sliceName] = {'sliceInfo': {'sliceName': sliceName}, 'parts': {}}
        sliceParts = twoDParts[sliceName]['parts']
        # Load in materials if we need them...
        matLib = qmt.Materials()
        slicePart = {}
        # Set material:
        if material is None:
            slicePart['material'] = None
        elif material not in self.modelDict['materials']:
            # The material needs to be generated (it's probably an alloy)
            self.modelDict['materials'][material] = matLib[material].serializeDict()
            slicePart['material'] = material
        else:
            slicePart['material'] = material
        # Set object type:
        if objType not in ['background', 'domain', 'boundary', None]:
            raise ValueError('objType not in list of known types.')
        else:
            slicePart['type'] = objType
        # Set domainType:
        if domainType not in ['semiconductor', 'metalFloating', 'metalGate', 'virtual',
                              'dielectric', None]:
            raise ValueError('domainType not in list of known types.')
        else:
            slicePart['domainType'] = domainType
        # Set band offset
        if bandOffset is not None:
            slicePart['bandOffset'] = bandOffset
        if surfaceChargeDensity is not None:
            slicePart['surfaceChargeDensity'] = surfaceChargeDensity
        if bulkDoping is not None:
            slicePart['bulkDoping'] = bulkDoping
        if subtractList is None:
            subtractList = []
        slicePart['subtractList'] = subtractList
        # Set boundary condition:
        slicePart['boundaryCondition'] = boundaryConditions
        # Set descriptors, used for misc., non-standard properties
        slicePart['descriptors'] = descriptors
        slicePart['geometry'] = geometry
        sliceParts[partName] = slicePart
        self.modelDict['buildOrder'][len(self.modelDict['buildOrder'])] = partName

    def addThomasFermi2dTask(self, region, grid, slice_name, name=None, temperature=0.):
        """Add a 2D Thomas-Fermi postprocessing task.

        @param region: 2D region to simulate. May simply be the name of a 2DPart (i.e. an entry in
            the model's slices dict), or a dict containing a boundingBox specification.
        @param grid: Grid specification dict. May have either a 'step_size' or 'steps' entry (to
            specify grid spacing in nm or number of grid steps per dimension), or separate 'x' and
            'y' dicts. May also specify an 'origin'.
        @param slice_name: Name of the slice (a key in the model's slices dict) to be simulated.
        @param name: Custom name for this task. Defaults to 'thomasFermi2d' concatenated with an
            integer ID.
        @param temperature: Temperature [in K] for the simulation.
        """
        task = {'task': 'thomasFermi2d', 'slice': slice_name}
        grid_spec = {'region': region}
        if np.isscalar(grid):
            grid_spec['step_size'] = grid
        else:
            grid_spec.update(grid)
        task['grid'] = grid_spec
        task['temperature'] = temperature
        # task name
        if 'tasks' not in self.modelDict['postProcess']:
            self.modelDict['postProcess']['tasks'] = {}
        if name is None:
            name = '%s%s' % (task['task'], len(self.modelDict['postProcess']['tasks']))
        task['name'] = name
        assert name not in self.modelDict['postProcess']['tasks']
        self.modelDict['postProcess']['tasks'][name] = task

    def addSchrodinger2dTask(self, region, grid, slice_name, eigenvalues=1, target_energy=None,
                             solver=None, name=None, write_wavefunctions=True,
                             plot_wavefunctions=True, temperature=0.):
        """Add a 2D Schrodinger postprocessing task.

        @param region: 2D region to simulate. May simply be the name of a 2DPart (i.e. an entry in
            the model's slices dict), or a dict containing a boundingBox specification.
        @param grid: Grid specification dict. May have either a 'step_size' or 'steps' entry (to
            specify grid spacing in nm or number of grid steps per dimension), or separate 'x' and
            'y' dicts. May also specify an 'origin'.
        @param slice_name: Name of the slice (a key in the model's slices dict) to be simulated.
        @param int eigenvalues: Number of eigenvalues to be targeted.
        @param float target_energy: Energy to be targeted in the sparse eigensolve. The default None
            targets lowest eigenstates.
        @param str solver: ('sparse'|'dense') for sparse or dense eigensolver.
        @param name: Custom name for this task. Defaults to 'schrodinger2d' concatenated with an
            integer ID.
        @param bool write_wavefunctions: Whether wave functions of eigenstates are to be written to
            disk.
        @param bool plot_wavefunctions: Whether wave functions of eigenstates are to be plotted.
        @param temperature: Temperature [in K] for the calculation of densities.
        """
        task = {'task': 'schrodinger2d',
                'slice': slice_name,
                'spectrum': {'eigenvalues': eigenvalues, 'target energy': target_energy},
                'wave functions': {'write': write_wavefunctions, 'plot': plot_wavefunctions}
                }
        grid_spec = {'region': region}
        if np.isscalar(grid):
            grid_spec['step_size'] = grid
        else:
            grid_spec.update(grid)
        task['grid'] = grid_spec
        if solver is not None:
            task['solver'] = solver
        task['temperature'] = temperature
        # task name
        if 'tasks' not in self.modelDict['postProcess']:
            self.modelDict['postProcess']['tasks'] = {}
        if name is None:
            name = '%s%s' % (task['task'], len(self.modelDict['postProcess']['tasks']))
        task['name'] = name
        assert name not in self.modelDict['postProcess']['tasks']
        self.modelDict['postProcess']['tasks'][name] = task

    def addPlotPotential2dTask(self, region, grid, slice_name, name=None):
        """Add a 2D Schrodinger postprocessing task.

        @param region: 2D region to plot. May simply be the name of a 2DPart (i.e. an entry in
            the model's slices dict), or a dict containing a boundingBox specification.
        @param grid: Grid specification dict. May have either a 'step_size' or 'steps' entry (to
            specify grid spacing in nm or number of grid steps per dimension), or separate 'x' and
            'y' dicts. May also specify an 'origin'.
        @param slice_name: Name of the slice (a key in the model's slices dict) to be plotted.
        @param name: Custom name for this task. Defaults to 'schrodinger2d' concatenated with an
            integer ID.
        """
        task = {'task': 'plotPotential2d', 'slice': slice_name}
        grid_spec = {'region': region}
        if np.isscalar(grid):
            grid_spec['step_size'] = grid
        else:
            grid_spec.update(grid)
        task['grid'] = grid_spec
        # task name
        if 'tasks' not in self.modelDict['postProcess']:
            self.modelDict['postProcess']['tasks'] = {}
        if name is None:
            name = '%s%s' % (task['task'], len(self.modelDict['postProcess']['tasks']))
        task['name'] = name
        assert name not in self.modelDict['postProcess']['tasks']
        self.modelDict['postProcess']['tasks'][name] = task

    def addSchrodingerTask(self, x, y, z, eigenvalues, target_energy=None, solver=None, name=None,
                           write_spectrum=True, write_wavefunctions=True, write_density=True,
                           plot_format=None, plot=True, plot_wavefunctions=True, efermi=0.):
        # instructions for Schrodinger solve
        task = {
            'task': 'schrodinger',
            'grid': {'x': x, 'y': y, 'z': z},
            'spectrum': {'eigenvalues': eigenvalues, 'target energy': target_energy,
                         'write': write_spectrum},
            'wave functions': {'write': write_wavefunctions},
            'density': {'write': write_density},
            'Fermi energy': efermi
        }
        if solver is not None:
            assert solver in ('sparse', 'dense')
            task['solver'] = solver
        # task name
        if 'tasks' not in self.modelDict['postProcess']:
            self.modelDict['postProcess']['tasks'] = {}
        if name is None:
            name = 'schrodinger%s' % len(self.modelDict['postProcess']['tasks'])
        # plots
        plots = {}
        if plot:
            plots['potential'] = {'file name': name + '_potential'}
            plots['density'] = {'file name': name + '_density'}
        if plot_wavefunctions:
            for i in range(eigenvalues):
                plots['psi %s' % i] = {'quantity': 'wave function', 'level index': i,
                                       'file name': name + '_psi%s' % i}
        if plot_format is not None:
            for plot in itervalues(plots):
                plot['format'] = plot_format
        task['plot'] = plots
        self.modelDict['postProcess']['tasks'][name] = task

    def addPlotPotentialTask(self, x, y, z, name=None, plot_format=None):
        if name is None:
            name = 'plot%s' % len(self.modelDict['postProcess']['tasks'])
        task = {
            'task': 'plot potential',
            'grid': {'x': x, 'y': y, 'z': z},
            'file name': name + '_potential'
        }
        if plot_format is not None:
            task['format'] = plot_format
        if 'tasks' not in self.modelDict['postProcess']:
            self.modelDict['postProcess']['tasks'] = {}
        self.modelDict['postProcess']['tasks'][name] = task

    def saveModel(self, customPath=None):
        '''Save the current model to disk.
            
            Keyword arguments
            ----------        
            customPath: str, default None
                If set, this overrides the path in self.modelPath.
        '''
        if customPath is None:
            myFile = open(self.modelPath, 'w')
        else:
            myFile = open(customPath, 'w')
        json.dump(self.modelDict, myFile)
        myFile.close()

    def loadModel(self, updateModel=True):
        '''Load the model from disk.

            Keyword arguments
            ----------
            updateModel : bool, default True
            If true, whatever is currently in the modelDict will be added to the
            loaded model on import. Repeated settings are overwritten. If false,
            the current state of modelDict will be wiped out and replaced by the
            loaded file.
        '''
        fileExists = os.path.isfile(self.modelPath)
        if fileExists:
            myFile = open(self.modelPath, 'r')
            modelDict = json.load(myFile)
            myFile.close()
        else:
            modelDict = self.genEmptyModelDict()
        if updateModel:
            for subDictKey in self.modelDict:
                modelDict[subDictKey].update(self.modelDict[subDictKey])
                self.modelDict = modelDict
        else:
            self.modelDict = modelDict

    def addJob(self, rootPath, jobSequence=None, numParallelJobs=1,numCoresPerJob=1,
               geoGenArgs={}, comsolRunMode='batch',
               postProcArgs={}):
        '''Add a job to the model.

            Parameters
            ----------
            rootPath : str
                Directory for the root of the job, where all sub-folders will 
                be written.

            Keyword arguments
            ----------
            jobSequence : list, default None
                Add a specified job sequence to the model. The valid sequence 
                nodes are:
                    geoGen : make geometries using FreeCAD.
                    mesh : mesh the geometries using COMSOL.
                    preProc : generate an interpolation grid corresponding to
                        a given density rule.
                    run : run a non-linear Poisson solve using COMSOL.
                    postProc : run post-processing routines.
                If left as None, this degaults to:
                ['geoGen','comsolRun','postProc']
            numParallelJobs : int, default 1
                Number of parallel jobs to run.
            numCoresPerJob : int, default 1
                Number of cores to use per job.
            geoGenArgs : dict, default {}
                Arguments for use by the geoGen nodes.        
            comsolRunArgs : dict, default {}
                Arguments for use by the run nodes.                
            postProcArgs : dict, default {}
                Arguments for use by the postProc nodes.                
        '''
        self.modelDict['jobSettings']['rootPath'] = rootPath
        if jobSequence is None:
            self.modelDict['jobSettings']['jobSequence'] = ['geoGen']
        else:
            self.modelDict['jobSettings']['jobSequence'] = jobSequence
        self.modelDict['jobSettings']['numParallelJobs'] = numParallelJobs
        self.modelDict['jobSettings']['numCoresPerJob'] = numCoresPerJob
        self.modelDict['jobSettings']['geoGenArgs'] = geoGenArgs
        self.modelDict['jobSettings']['comsolRunMode'] = comsolRunMode
        self.modelDict['jobSettings']['postProcArgs'] = postProcArgs

    def setPaths(self, COMSOLExecPath=None, COMSOLCompilePath=None,
                 mpiPath=None, pythonPath=None, jdkPath=None, freeCADPath=None):
        '''Set up paths to execuables.

            Keword Arguments
            ----------
            COMSOLExecPath : str, default None
                Path to the COMSOL command to be run, typically 
                comsolclusterbatch.            
            COMSOLCompilePath : str, default None
                Path to the COMSOL Java compiler
            mpiPath : str, default None
                Path to mpiexec
            jdkPath : str, default None
                Path to the jdk installation
        '''
        self.modelDict['pathSettings']['COMSOLExecPath'] = COMSOLExecPath
        self.modelDict['pathSettings']['COMSOLCompilePath'] = COMSOLCompilePath
        self.modelDict['pathSettings']['mpiPath'] = mpiPath
        self.modelDict['pathSettings']['pythonPath'] = pythonPath
        self.modelDict['pathSettings']['jdkPath'] = jdkPath
        self.modelDict['pathSettings']['freeCADPath'] = freeCADPath
