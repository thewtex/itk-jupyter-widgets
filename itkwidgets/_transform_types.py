__all__ = ['to_spatial_image', 'to_point_set', 'to_geometry',
           'spatial_image_from_array', 'image_from_xarray', 'xarray_from_image']

import itk
import numpy as np
import xarray as xr


def is_arraylike(arr):
    return hasattr(arr, 'shape') and \
        hasattr(arr, 'dtype') and \
        hasattr(arr, '__array__') and \
        hasattr(arr, 'ndim')

# from IPython.core.debugger import set_trace

have_imagej = False
try:
    import imagej  # noqa: F401
    have_imagej = True
except ImportError:
    pass
have_vtk = False
try:
    import vtk
    have_vtk = True
except ImportError:
    pass
have_dask = False
try:
    import dask.array
    have_dask = True
except ImportError:
    pass
have_simpleitk = False
try:
    import SimpleITK as sitk
    have_simpleitk = True
except ImportError:
    pass
have_skan = False
try:
    import skan
    have_skan = True
except ImportError:
    pass

_itk_pixel_to_vtkjs_type_components = {
    itk.SC: ('Int8Array', 1),
    itk.UC: ('Uint8Array', 1),
    itk.SS: ('Int16Array', 1),
    itk.US: ('Uint16Array', 1),
    itk.SI: ('Int32Array', 1),
    itk.UI: ('Uint32Array', 1),
    itk.F: ('Float32Array', 1),
    itk.D: ('Float64Array', 1),
}


def _vtk_to_vtkjs(data_array):
    from vtk.util.numpy_support import vtk_to_numpy
    # From vtkType.h
    _vtk_data_type_to_vtkjs_type = {
        2: 'Int8Array',
        15: 'Int8Array',
        3: 'Uint8Array',
        4: 'Int16Array',
        5: 'Uint16Array',
        6: 'Int32Array',
        7: 'Uint32Array',
        8: 'BigInt64Array',
        9: 'BigUint64Array',
        10: 'Float32Array',
        11: 'Float64Array',
        16: 'BigInt64Array',
        17: 'BigUint64Array',
    }
    vtk_data_type = data_array.GetDataType()
    data_type = _vtk_data_type_to_vtkjs_type[vtk_data_type]
    numpy_array = vtk_to_numpy(data_array)
    if vtk_data_type == 8 or vtk_data_type == 16:
        ii32 = np.iinfo(np.int32)
        value_range = data_array.GetValueRange()
        if value_range[0] < ii32.min or value_range[1] > ii32.max:
            raise ValueError(
                '64 integers are not supported yet by WebGL / vtk.js')
        numpy_array = numpy_array.astype(np.int32)
        data_type = 'Int32Array'
    elif vtk_data_type == 9 or vtk_data_type == 17:
        ui32 = np.iinfo(np.uint32)
        value_range = data_array.GetValueRange()
        if value_range[0] < ui32.min or value_range[1] > ui32.max:
            raise ValueError(
                '64 integers are not supported by WebGL / vtk.js yet')
        numpy_array = numpy_array.astype(np.uint32)
        data_type = 'Uint32Array'

    return data_type, numpy_array


def _vtk_data_attributes_to_vtkjs(attributes):
    vtkjs_attributes = {"vtkClass": "vtkDataSetAttributes"}
    arrays = []
    for array_index in range(attributes.GetNumberOfArrays()):
        vtk_array = attributes.GetArray(array_index)
        data_type, values = _vtk_to_vtkjs(vtk_array)
        array = {"data": {
            'vtkClass': 'vtkDataArray',
            'name': vtk_array.GetName(),
            'numberOfComponents': vtk_array.GetNumberOfComponents(),
            'size': vtk_array.GetSize(),
            'dataType': data_type,
            'values': values}}
        scalars = attributes.GetScalars()
        if scalars and scalars.GetName() == vtk_array.GetName():
            vtkjs_attributes['activeScalars'] = array_index
        globalIds = attributes.GetGlobalIds()
        if globalIds and globalIds.GetName() == vtk_array.GetName():
            vtkjs_attributes['activeGlobalIds'] = array_index
        normals = attributes.GetNormals()
        if normals and normals.GetName() == vtk_array.GetName():
            vtkjs_attributes['activeNormals'] = array_index
        pedigreeIds = attributes.GetPedigreeIds()
        if pedigreeIds and pedigreeIds.GetName() == vtk_array.GetName():
            vtkjs_attributes['activePedigreeIds'] = array_index
        tCoords = attributes.GetTCoords()
        if tCoords and tCoords.GetName() == vtk_array.GetName():
            vtkjs_attributes['activeTCoords'] = array_index
        vectors = attributes.GetVectors()
        if vectors and vectors.GetName() == vtk_array.GetName():
            vtkjs_attributes['activeVectors'] = array_index
        arrays.append(array)
    vtkjs_attributes["arrays"] = arrays
    return vtkjs_attributes


def xarray_from_image(image):
    array_view = itk.array_view_from_image(image)
    spacing = itk.spacing(image)
    origin = itk.origin(image)
    size = itk.size(image)
    direction = np.transpose(itk.array_from_matrix(image.GetDirection()))
    spatial_dimension = image.GetImageDimension()

    spatial_dims = ('x', 'y', 'z')
    coords = {}
    for index, dim in enumerate(spatial_dims[:spatial_dimension]):
        coords[dim] = np.arange(origin[index],
                                origin[index] + size[index]*spacing[index],
                                spacing[index],
                                dtype=np.float64)

    dims = list(reversed(spatial_dims[:spatial_dimension]))
    components = image.GetNumberOfComponentsPerPixel()
    if components > 1:
        dims.append('c')
        coords['c'] = np.arange(components, dtype=np.uint64)

    data_array = xr.DataArray(array_view,
                              dims=dims,
                              coords=coords,
                              attrs={'direction': direction})
    return data_array

def image_from_xarray(xarray):
    spatial_dims = list(set(('z', 'y', 'x')).intersection(set(xarray.dims)))
    spatial_dims.sort(reverse=True)
    spatial_dimension = len(spatial_dims)
    # Todo: check dims order, flip as needed

    is_vector = False
    if spatial_dimension < len(xarray.dims):
        is_vector = True
    # Dask array -> NumPy ndarray as needed
    ndarray = np.asarray(xarray.values)
    itk_image = itk.image_view_from_array(ndarray, is_vector=is_vector)

    origin = [0.0]*spatial_dimension
    spacing = [1.0]*spatial_dimension
    for index in range(spatial_dimension):
        dim = spatial_dims[index]
        origin[index]
        spacing[index] = xarray.coords[dim][1] - xarray.coords[dim][0]
    itk_image.SetSpacing(spacing)
    itk_image.SetOrigin(origin)
    if 'direction' in xarray.attrs:
        direction = xarray.attrs['direction']
        itk_image.SetDirection(np.transpose(direction))

    return itk_image


def si_index_to_position(image, spatial_dims, indices):
    """
    image: xarray spatial image
    spatial_dims: sequence of spatial dims in zyx order
    indices: integer data array indices corresponding to the spatial dims

    returns: position in world space
    """
    # coords = origin + spacing * index
    # position = direction * (coords - origin) + origin
    origin = [image.coords[dim][0] for dim in spatial_dims]
    origin = np.asarray(origin)
    coords = [image.coords[dim][index] for dim, index in zip(spatial_dims, indices)]
    coords = np.asarray(coords)
    direction = image.attrs['direction']
    position = np.matmul(direction, coords - origin) + origin
    return position

def si_position_to_index(image, spatial_dims, position):
    """
    image: xarray spatial image
    spatial_dims: sequence of spatial dims in zyx order
    positions: position in world space corresponding to the spatial dims

    returns: index into data array
    """
    # coords = origin + spacing * index
    # position = direction * (coords - origin) + origin
    origin = [image.coords[dim][0] for dim in spatial_dims]
    origin = np.asarray(origin)
    direction_inv = np.linalg.inv(image.attrs['direction'])
    offset = np.matmul(direction_inv, position - origin)
    coords = offset + origin
    indices = [image.indexes[dim].get_loc(c, method='nearest')
               for dim, c in zip(spatial_dims, coords)]
    return indices



def spatial_image_from_array(array):
    """Generate an xarray spatial image from a NumPy array-like.

    Todo: kwargs to specify dims, coords, direction"""
    shape = array.shape
    # Start by assuming all spatial dimensions
    spatial_dimension = len(shape)
    direction = np.eye(spatial_dimension)
    spatial_dims = ('z', 'y', 'x')
    coords = {}
    for index, dim in enumerate(spatial_dims[-spatial_dimension:]):
        coords[dim] = np.arange(0.0,
                                shape[index],
                                1.0,
                                dtype=np.float64)

    dims = list(spatial_dims[-spatial_dimension:])

    data_array = xr.DataArray(array,
                              dims=dims,
                              coords=coords,
                              attrs={'direction': direction,})
    return data_array


def to_spatial_image(image_like):
    if isinstance(image_like, xr.DataArray):
        # Check si.is_spatial_image(image_like)
        return image_like
    elif isinstance(image_like, itk.Object):
        # an itk.Image or a filter that produces an Image
        itk_image = itk.output(image_like)
        spatial_image = xarray_from_image(itk_image)
        return spatial_image
    elif is_arraylike(image_like):
        return spatial_image_from_array(image_like)
    elif have_vtk and isinstance(image_like, vtk.vtkImageData):
        from vtk.util import numpy_support as vtk_numpy_support
        array = vtk_numpy_support.vtk_to_numpy(
            image_like.GetPointData().GetScalars())
        array.shape = tuple(image_like.GetDimensions())[::-1]
        image_from_array = itk.image_view_from_array(array)
        image_from_array.SetSpacing(image_like.GetSpacing())
        image_from_array.SetOrigin(image_like.GetOrigin())
        return xarray_from_image(image_from_array)
    elif have_simpleitk and isinstance(image_like, sitk.Image):
        array = sitk.GetArrayViewFromImage(image_like)
        image_from_array = itk.image_view_from_array(array)
        image_from_array.SetSpacing(image_like.GetSpacing())
        image_from_array.SetOrigin(image_like.GetOrigin())
        direction = image_like.GetDirection()
        npdirection = np.asarray(direction)
        npdirection = np.reshape(npdirection, (-1, 3))
        itkdirection = itk.matrix_from_array(npdirection)
        image_from_array.SetDirection(itkdirection)
        return xarray_from_image(image_from_array)
    elif have_imagej:
        import imglyb
        if isinstance(image_like,
                      imglyb.util.ReferenceGuardingRandomAccessibleInterval):
            array = imglyb.to_numpy(image_like)
            image_from_array = itk.image_view_from_array(array)
            return xarray_from_image(image_from_array)

    return None


def to_point_set(point_set_like):  # noqa: C901
    if isinstance(point_set_like, itk.PointSet):
        if not hasattr(itk, 'PyVectorContainer'):
            raise ImportError(
                'itk.MeshToPolyDataFilter is not available -- install the itk-meshtopolydata package')
        itk_polydata = itk.mesh_to_poly_data_filter(point_set_like)

        point_set = {'vtkClass': 'vtkPolyData'}

        points = itk_polydata.GetPoints()
        point_template = itk.template(points)
        element_type = point_template[1][1]
        # todo: test array_view here and below
        point_values = itk.PyVectorContainer[element_type].array_from_vector_container(
            points)
        if len(
                point_values.shape) > 1 and point_values.shape[1] == 2 or point_values.shape[1] == 3:
            if point_values.shape[1] == 2:
                point_values = np.hstack(
                    (point_values, -5.0e-6 * np.ones((point_values.shape[0], 1)))).astype(np.float32)
            points = {'vtkClass': 'vtkPoints',
                      'numberOfComponents': 3,
                      'dataType': 'Float32Array',
                      'size': point_values.size,
                      'values': point_values}
            point_set['points'] = points
        else:
            return None

        itk_point_data = itk_polydata.GetPointData()
        if itk_point_data and itk_point_data.Size():
            pixel_type = itk.template(itk_polydata)[1][0]
            data_type, number_of_components = _itk_pixel_to_vtkjs_type_components[pixel_type]
            data = itk.PyVectorContainer[pixel_type].array_from_vector_container(
                itk_point_data)
            point_data = {
                "vtkClass": "vtkDataSetAttributes",
                "activeScalars": 0,
                "arrays": [
                    {"data": {
                        'vtkClass': 'vtkDataArray',
                        'name': 'Point Data',
                        'numberOfComponents': number_of_components,
                        'size': data.size,
                        'dataType': data_type,
                        'values': data}
                     }],
            }
            point_set['pointData'] = point_data

        return point_set
    elif is_arraylike(point_set_like):
        point_values = np.asarray(point_set_like).astype(np.float32)
        if len(
                point_values.shape) > 1 and point_values.shape[1] == 2 or point_values.shape[1] == 3:
            if point_values.shape[1] == 2:
                point_values = np.hstack(
                    (point_values, -5.0e-6 * np.ones((point_values.shape[0], 1)))).astype(np.float32)
            point_set = {'vtkClass': 'vtkPolyData'}
            points = {'vtkClass': 'vtkPoints',
                      'name': '_points',
                      'numberOfComponents': 3,
                      'dataType': 'Float32Array',
                      'size': point_values.size,
                      'values': point_values}
            point_set['points'] = points
            vert_values = np.ones((point_values.size * 2,), dtype=np.uint32)
            vert_values[1::2] = np.arange(point_values.size)
            verts = {'vtkClass': 'vtkCellArray',
                     'name': '_verts',
                     'numberOfComponents': 1,
                     'dataType': 'Uint32Array',
                     'size': vert_values.size,
                     'values': vert_values}
            point_set['verts'] = verts
            return point_set
        else:
            return None
    elif have_vtk and isinstance(point_set_like, vtk.vtkPolyData):
        from vtk.util.numpy_support import vtk_to_numpy
        point_set = {'vtkClass': 'vtkPolyData'}

        points_data = vtk_to_numpy(point_set_like.GetPoints().GetData())
        points_data = points_data.astype(np.float32).ravel()
        points = {'vtkClass': 'vtkPoints',
                  'name': '_points',
                  'numberOfComponents': 3,
                  'dataType': 'Float32Array',
                  'size': points_data.size,
                  'values': points_data}
        point_set['points'] = points

        vtk_verts = point_set_like.GetVerts()
        if vtk_verts.GetNumberOfCells():
            data = vtk_to_numpy(vtk_verts.GetData())
            data = data.astype(np.uint32).ravel()
            cells = {'vtkClass': 'vtkCellArray',
                     'name': '_' + 'verts',
                     'numberOfComponents': 1,
                     'size': data.size,
                     'dataType': 'Uint32Array',
                     'values': data}
            point_set['verts'] = cells
        vtk_point_data = point_set_like.GetPointData()
        if vtk_point_data and vtk_point_data.GetNumberOfArrays():
            vtkjs_point_data = _vtk_data_attributes_to_vtkjs(vtk_point_data)
            point_set['pointData'] = vtkjs_point_data

        vtk_cell_data = point_set_like.GetCellData()
        if vtk_cell_data and vtk_cell_data.GetNumberOfArrays():
            vtkjs_cell_data = _vtk_data_attributes_to_vtkjs(vtk_cell_data)
            point_set['cellData'] = vtkjs_cell_data

        return point_set

    return None


def to_geometry(geometry_like):  # noqa: C901
    if isinstance(geometry_like, itk.Mesh):
        if not hasattr(itk, 'PyVectorContainer'):
            raise ImportError(
                'itk.MeshToPolyDataFilter is not available -- install the itk-meshtopolydata package')
        itk_polydata = itk.mesh_to_poly_data_filter(geometry_like)

        geometry = {'vtkClass': 'vtkPolyData'}

        points = itk_polydata.GetPoints()
        point_template = itk.template(points)
        element_type = point_template[1][1]
        # todo: test array_view here and below
        point_values = itk.PyVectorContainer[element_type].array_from_vector_container(
            points)
        if len(
                point_values.shape) > 1 and point_values.shape[1] == 2 or point_values.shape[1] == 3:
            if point_values.shape[1] == 2:
                point_values.resize((point_values.shape[0], 3))
                point_values[:, 2] = 0.0
            points = {'vtkClass': 'vtkPoints',
                      'numberOfComponents': 3,
                      'dataType': 'Float32Array',
                      'size': point_values.size,
                      'values': point_values}
            geometry['points'] = points
        else:
            return None

        itk_verts = itk_polydata.GetVertices()
        itk_lines = itk_polydata.GetLines()
        itk_polys = itk_polydata.GetPolygons()
        itk_strips = itk_polydata.GetTriangleStrips()
        for cell_type, itk_cells in [('verts', itk_verts), ('lines', itk_lines),
                                     ('polys', itk_polys), ('strips', itk_strips)]:
            if itk_cells.Size():
                data = itk.PyVectorContainer[itk.UI].array_from_vector_container(
                    itk_cells)
                cells = {'vtkClass': 'vtkCellArray',
                         'name': '_' + cell_type,
                         'numberOfComponents': 1,
                         'size': data.size,
                         'dataType': 'Uint32Array',
                         'values': data}
                geometry[cell_type] = cells

        itk_point_data = itk_polydata.GetPointData()
        if itk_point_data and itk_point_data.Size():
            pixel_type = itk.template(itk_polydata)[1][0]
            data_type, number_of_components = _itk_pixel_to_vtkjs_type_components[pixel_type]
            data = itk.PyVectorContainer[pixel_type].array_from_vector_container(
                itk_point_data)
            point_data = {
                "vtkClass": "vtkDataSetAttributes",
                "activeScalars": 0,
                "arrays": [
                    {"data": {
                        'vtkClass': 'vtkDataArray',
                        'name': 'Point Data',
                        'numberOfComponents': number_of_components,
                        'size': data.size,
                        'dataType': data_type,
                        'values': data}
                     }],
            }
            geometry['pointData'] = point_data
        itk_cell_data = itk_polydata.GetCellData()
        if itk_cell_data and itk_cell_data.Size():
            pixel_type = itk.template(itk_polydata)[1][0]
            data_type, number_of_components = _itk_pixel_to_vtkjs_type_components[pixel_type]
            data = itk.PyVectorContainer[pixel_type].array_from_vector_container(
                itk_cell_data)
            cell_data = {
                "vtkClass": "vtkDataSetAttributes",
                "activeScalars": 0,
                "arrays": [
                    {"data": {
                        'vtkClass': 'vtkDataArray',
                        'name': 'Cell Data',
                        'numberOfComponents': number_of_components,
                        'size': data.size,
                        'dataType': data_type,
                        'values': data}
                     }],
            }
            geometry['cellData'] = cell_data

        return geometry
    elif isinstance(geometry_like, itk.PolyLineParametricPath):
        vertex_list = geometry_like.GetVertexList()
        number_of_points = vertex_list.Size()
        geometry = {'vtkClass': 'vtkPolyData'}

        points_data = -5.0e-6 * \
            np.ones((number_of_points, 3), dtype=np.float64)
        dimension = len(vertex_list.GetElement(0))
        # Todo: replace with itk.PyVectorContainer direct NumPy conversion
        for index in range(number_of_points):
            points_data[index, :dimension] = vertex_list.GetElement(index)
        points_data = points_data.astype(np.float32).ravel()
        points = {'vtkClass': 'vtkPoints',
                  'name': '_points',
                  'numberOfComponents': 3,
                  'dataType': 'Float32Array',
                  'size': points_data.size,
                  'values': points_data}
        geometry['points'] = points

        verts_data = np.ones((2 * number_of_points,), dtype=np.uint32)
        verts_data[1::2] = np.arange(number_of_points, dtype=np.uint32)

        lines_data = 2 * \
            np.ones((3 * (number_of_points - 1),), dtype=np.uint32)
        lines_data[1::3] = np.arange(number_of_points - 1, dtype=np.uint32)
        lines_data[2::3] = np.arange(1, number_of_points, dtype=np.uint32)

        # For cell_type, cell_data in [('verts', verts_data),]:
        for cell_type, cell_data in [
                ('verts', verts_data), ('lines', lines_data)]:
            cells = {'vtkClass': 'vtkCellArray',
                     'name': '_' + cell_type,
                     'numberOfComponents': 1,
                     'size': cell_data.size,
                     'dataType': 'Uint32Array',
                     'values': cell_data}
            geometry[cell_type] = cells

        return geometry
    elif have_skan and isinstance(geometry_like, skan.csr.Skeleton):

        geometry = {'vtkClass': 'vtkPolyData'}

        number_of_points = geometry_like.coordinates.shape[0]
        dimension = geometry_like.coordinates.shape[1]

        points_data = -5.0e-6 * \
            np.ones((number_of_points, 3), dtype=np.float64)
        points_data[:, :dimension] = np.flip(geometry_like.coordinates[:, :dimension], 1)
        points_data = points_data.astype(np.float32).ravel()
        points = {'vtkClass': 'vtkPoints',
                  'name': '_points',
                  'numberOfComponents': 3,
                  'dataType': 'Float32Array',
                  'size': points_data.size,
                  'values': points_data}
        geometry['points'] = points

        verts_data = np.empty((0,), dtype=np.uint32)
        lines_data = np.empty((0,), dtype=np.uint32)
        for path in geometry_like.paths_list():
            path_number_of_points = len(path)
            verts = np.ones((2 * path_number_of_points,), dtype=np.uint32)
            verts[1::2] = np.array(path, dtype=np.uint32)
            verts_data = np.concatenate((verts_data, verts))

            lines = 2 * \
                np.ones((3 * (path_number_of_points - 1),), dtype=np.uint32)
            lines[1::3] = np.array(path[:-1], dtype=np.uint32)
            lines[2::3] = np.array(path[1:], dtype=np.uint32)
            lines_data = np.concatenate((lines_data, lines))

        for cell_type, cell_data in [
                ('verts', verts_data), ('lines', lines_data)]:
            cells = {'vtkClass': 'vtkCellArray',
                     'name': '_' + cell_type,
                     'numberOfComponents': 1,
                     'size': cell_data.size,
                     'dataType': 'Uint32Array',
                     'values': cell_data}
            geometry[cell_type] = cells

        return geometry
    elif have_vtk and isinstance(geometry_like, vtk.vtkPolyData):
        from vtk.util.numpy_support import vtk_to_numpy

        geometry = {'vtkClass': 'vtkPolyData'}

        points_data = vtk_to_numpy(geometry_like.GetPoints().GetData())
        points_data = points_data.astype(np.float32).ravel()
        points = {'vtkClass': 'vtkPoints',
                  'name': '_points',
                  'numberOfComponents': 3,
                  'dataType': 'Float32Array',
                  'size': points_data.size,
                  'values': points_data}
        geometry['points'] = points

        vtk_verts = geometry_like.GetVerts()
        vtk_lines = geometry_like.GetLines()
        vtk_polys = geometry_like.GetPolys()
        vtk_strips = geometry_like.GetStrips()
        for cell_type, vtk_cells in [('verts', vtk_verts), ('lines', vtk_lines),
                                     ('polys', vtk_polys), ('strips', vtk_strips)]:
            if vtk_cells.GetNumberOfCells():
                data = vtk_to_numpy(vtk_cells.GetData())
                data = data.astype(np.uint32).ravel()
                cells = {'vtkClass': 'vtkCellArray',
                         'name': '_' + cell_type,
                         'numberOfComponents': 1,
                         'size': data.size,
                         'dataType': 'Uint32Array',
                         'values': data}
                geometry[cell_type] = cells
        vtk_point_data = geometry_like.GetPointData()
        if vtk_point_data and vtk_point_data.GetNumberOfArrays():
            vtkjs_point_data = _vtk_data_attributes_to_vtkjs(vtk_point_data)
            geometry['pointData'] = vtkjs_point_data

        vtk_cell_data = geometry_like.GetCellData()
        if vtk_cell_data and vtk_cell_data.GetNumberOfArrays():
            vtkjs_cell_data = _vtk_data_attributes_to_vtkjs(vtk_cell_data)
            geometry['cellData'] = vtkjs_cell_data

        return geometry
    elif have_vtk and isinstance(geometry_like, (vtk.vtkUnstructuredGrid,
                                                 vtk.vtkStructuredGrid,
                                                 vtk.vtkRectilinearGrid,
                                                 vtk.vtkImageData)):
        geometry_filter = vtk.vtkGeometryFilter()
        geometry_filter.SetInputData(geometry_like)
        geometry_filter.Update()
        geometry = to_geometry(geometry_filter.GetOutput())
        return geometry

    return None
