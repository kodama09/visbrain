import numpy as np
from warnings import warn

from vispy import gloo
from vispy.visuals import Visual
from vispy.geometry import MeshData
import vispy.visuals.transforms as vist

from visbrain.vbrain.utils import *


__all__ = ['BrainMeshVisual']




VERT_SHADER = """
#version 120
varying vec3 v_position;
varying vec4 v_color;
varying vec3 v_normal;

void main() {
    v_position = $a_position;
    v_normal = $a_normal;
    v_color = $a_color * $u_color;
    gl_Position = $transform(vec4($a_position, 1));
}
"""


FRAG_SHADER = """
#version 120
varying vec3 v_position;
varying vec4 v_color;
varying vec3 v_normal;

void main() {

    // ----------------- Ambient light -----------------
    vec3 ambientLight = $u_coefAmbient * v_color.rgb * $u_light_intensity;


    // ----------------- Diffuse light -----------------
    // Calculate the vector from this pixels surface to the light source
    vec3 surfaceToLight = $u_light_position - v_position;

    // Calculate the cosine of the angle of incidence
    float brightness = dot(v_normal, surfaceToLight) / (length(surfaceToLight) * length(v_normal));
    // brightness = clamp(brightness, 0, 1);
    brightness = max(min(brightness,1.0),0.0);

    // Get diffuse light :
    vec3 diffuseLight =  v_color.rgb * brightness * $u_light_intensity;


    // ----------------- Specular light -----------------
    vec3 surfaceToCamera = vec3(0.0, 0.0, 1.0) - v_position;
    vec3 K = normalize(normalize(surfaceToLight) + normalize(surfaceToCamera));
    float specular = clamp(pow(abs(dot(v_normal, K)), 40.), 0.0, 1.0);
    vec3 specularLight = $u_coefSpecular * specular * vec3(1., 1., 1.) * $u_light_intensity;


    // ----------------- Attenuation -----------------
    // float att = 0.0001;
    // float distanceToLight = length($u_light_position - v_position);
    // float attenuation = 1.0 / (1.0 + att * pow(distanceToLight, 2));


    // ----------------- Linear color -----------------
    // Without attenuation :
    vec3 linearColor = ambientLight + specularLight + diffuseLight;

    // With attenuation :
    // vec3 linearColor = ambientLight + attenuation*(specularLight + diffuseLight);
    

    // ----------------- Gamma correction -----------------
    // vec3 gamma = vec3(1.0/1.2);


    // ----------------- Final color -----------------
    // Without gamma correction :
    gl_FragColor = vec4(linearColor, v_color.a);

    // With gamma correction :
    // gl_FragColor = vec4(pow(linearColor, gamma), v_color.a);
}
"""


class BrainMeshVisual(Visual):
    """Main visual class from brain mesh

    Args:
        name: type
            description

    Kargs:
        name: type, optional, (def: default)
            description 

    Return
        name: description
    """

    def __len__(self):
        return len(self._vertFaces)

    def __iter__(self):
        pass

    def __getitem__(self):
        pass

    def __init__(self, vertices=None, faces=None, normals=None, vertex_colors=None, camera=None,
                 meshdata=None, l_position=(1., 1., 1.), l_color=(1., 1., 1., 1.), l_intensity=(1., 1., 1.),
                 l_coefAmbient=0.07, l_coefSpecular=0.5, scale_factor=10, hemisphere='both', recenter=True):
        Visual.__init__(self, vcode=VERT_SHADER, fcode=FRAG_SHADER)

        # Usefull variables :
        self._scaleFactor = scale_factor
        self._btransform = vist.ChainTransform([vist.NullTransform()])

        # Define buffers
        self._vertices = gloo.VertexBuffer(np.zeros((0, 3), dtype=np.float32))
        self._normals = None
        self._faces = gloo.IndexBuffer()
        self._colors = gloo.VertexBuffer(np.zeros((0, 4), dtype=np.float32))
        self._normals = gloo.VertexBuffer(np.zeros((0, 3), dtype=np.float32))
        self._color_changed = False
        self._hemisphere = hemisphere
        self._recenter = recenter

        # Set the data :
        BrainMeshVisual.set_data(self, vertices=vertices, faces=faces, normals=normals,
                                 meshdata=meshdata, vertex_colors=vertex_colors, hemisphere=hemisphere)

        # Set the light :
        BrainMeshVisual.set_light(self, l_position=l_position, l_color=l_color, l_intensity=l_intensity,
                                  l_coefAmbient=l_coefAmbient, l_coefSpecular=l_coefSpecular)

        # Set camera :
        BrainMeshVisual.set_camera(self, camera)


        self.set_gl_state('translucent', depth_test=True, cull_face=False, blend=True,
                          blend_func=('src_alpha', 'one_minus_src_alpha'))
        self._draw_mode = 'triangles'

        self.freeze()

    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    # Methods when data/camera/light changed
    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    def mesh_data_changed(self):
        """Tell if data changed"""
        self._data_changed = True
        self.update()

    def mesh_color_changed(self):
        """Tell if color changed"""
        self._color_changed = True
        self.update()

    def mesh_light_changed(self):
        """Tell if light changed"""
        self._light_changed = True
        self.update()

    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    # Set data/light/camera
    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    def set_data(self, vertices=None, faces=None, normals=None, invert_normals=False,
                 meshdata=None, vertex_colors=None, color=None, hemisphere='both'):
        """Set data to the mesh

        Kargs:
            vertices: ndarray, optional, (def: None)
                Vertices to set of shape (N, 3) or (M, 3)

            faces: ndarray, optional, (def: None)
                Faces to set of shape (M, 3)

            normals: ndarray, optional, (def: None)
                The normals to set (same shape as vertices)

            invert_normals: bool, optional, (def: False)
                Sometimes it appear that the brain color is full
                black. In that case, turn this parameter to True
                in order to invert normals.

            meshdata: vispy.meshdata, optional, (def: None)
                Custom vispy mesh data

            vertex_colors: ndarray, optional, (def: None)
                Vertex color of shape (N, 4) or (M, 3, 4)

            color: tuple/string/hex, optional, (def: None)
                Alternatively, you can specify a uniform color.

            hemisphere: string, optional, (def: 'both')
                Choose if an hemisphere has to be selected ('both', 'left', 'right')
        """
        # -------------- Check inputs --------------
        # Check if faces index start at zero (Matlab like):
        if faces.min() != 0:
            faces -= faces.min().astype('uint32')

        # Invert normals :
        if invert_normals:
            norm_coef = -1
        else:
            norm_coef = 1

        # -------------- Vertices/Faces/Normals --------------
        # Everything to None:
        if (vertices is None) and (faces is None) and (meshdata is None):
            raise ValueError('You should at least enter vertices and faces or MeshData.')

        # Only vertices and faces :
        if (vertices is not None) and (faces is not None) and (normals is None):
            md = MeshData(vertices=vertices, faces=faces)
            vertices = md.get_vertices(indexed='faces')
            normals = md.get_vertex_normals(indexed='faces')

        # Custom meshdata :
        if meshdata is not None:
            vertices = meshdata.get_vertices(indexed='faces')
            faces = meshdata.get_faces()
            normals = meshdata.get_vertex_normals(indexed='faces')


        # -------------- Vertices color --------------
        # Wrong shape for vertex color :
        if (vertex_colors is not None) and (vertex_colors.shape != (faces.shape[0], 3, 4)):
            warn('Wrong shape for vertex color. Default color will be used instead.')
            vertex_colors = None

        # No vertex color :
        if vertex_colors is None:
            vertex_colors = np.ones((faces.shape[0], 3, 4), dtype=np.float32)

        # Uniform color :
        if color is not None:
            vertex_colors = np.tile(color2vb(color)[np.newaxis, ...], (faces.shape[0], 3, 1))

        # -------------- Transformations --------------
        if self._recenter:
            # Inspect minimum and maximum :
            vm, vM = vertices.min(), vertices.max()

            # Normalize by scaleFactor/max :
            vertices = normalize(vertices, tomin=-self._scaleFactor, tomax=self._scaleFactor)

            # Recenter the brain around (0, 0, 0) :
            xScale, yScale, zScale = vertices[:, :, 0].mean(), vertices[:, :, 1].mean(), vertices[:, :, 2].mean()
            np.subtract(vertices[:, :, 0], xScale, out=vertices[:, :, 0])
            np.subtract(vertices[:, :, 1], yScale, out=vertices[:, :, 1])
            np.subtract(vertices[:, :, 2], zScale, out=vertices[:, :, 2])


            # Save it in a transformation :
            self._btransform.prepend(vist.STTransform(translate=[-vM]*3))
            self._btransform.prepend(vist.STTransform(scale=[2*self._scaleFactor/(vM-vm)]*3))
            self._btransform.prepend(vist.STTransform(translate=[self._scaleFactor]*3))
            self._btransform.prepend(vist.STTransform(translate=[-xScale, -yScale, -zScale]))

            # Keep maximum/minimum pear coordinates :
            self._vertsize = [(vertices[:, 0, 0].min(), vertices[:, 0, 0].max()),
                              (vertices[:, 1, 0].min(), vertices[:, 1, 0].max()),
                              (vertices[:, 2].min(), vertices[:, 2].max())]

        # Load only left/ritgh hemisphere :
        if hemisphere in ['left', 'right']:
            if hemisphere == 'left':
                inf = np.where(vertices[..., 0] <= vertices[:, :, 0].mean())[0]
            if hemisphere == 'right':
                inf = np.where(vertices[..., 0] >= vertices[:, :, 0].mean())[0]
            vertices = vertices[inf, ...]
            faces = faces[inf, ...]
            normals = normals[inf, ...]
            vertex_colors = vertex_colors[inf, ...]

        # -------------- Convert elements --------------
        # Assign elements :
        self._vertFaces = np.ascontiguousarray(vertices, dtype=np.float32)
        self._colFaces = np.ascontiguousarray(vertex_colors, dtype=np.float32)
        self._normFaces = np.ascontiguousarray(norm_coef*normals, dtype=np.float32)
        self._tri = faces.astype('uint32')

        self.mesh_data_changed()


    def set_color(self, data=None, color='white', cmap='viridis', dynamic=None,
                  alpha=1.0, vmin=None, vmax=None, under='dimgray', over='darkred'):
        """Set specific colors on the brain

        Args:
            data: None
                Data to use for the color. If data is None

        Kargs:
            data: np.ndarray, optional, (def: None)
                Data to use for the color. If data is None, the color will
                be uniform using the color parameter. If data is a vector,
                the color is going to be deduced from this vector. If data
                is a (N, 4) it will be interpreted as a color. 

            color: tuple/string/hex, optional, (def: 'white')
                The default uniform color

            cmap: string, optional, (def: 'viridis')
                Colormap to use if data is a vector

            dynamic: float, optional, (def: None)
                Control the dynamic of colors

            alpha: float, optional, (def: 1.0)
                Opacity to use if data is a vector

            vmin/vmax: float, optional, (def: None)
                Minimum/maximum value for clipping

            under/over: tuple/string/hex, optional, (def: 'dimgray'/'darkred')
                Color to use under/over respectively vmin/max
        """ 
        # Color to RGBA :
        color = color2vb(color, len(self))

        # Color management :
        if data is None: # uniform color
            col = np.tile(color, (len(self), 1)).astype(np.float32)
        elif data.ndim == 1: # data vector
            col = array2colormap(data.copy(), cmap=cmap, alpha=alpha, vmin=vmin, vmax=vmax,
                                 under=under, over=over).astype(np.float32)
            # Dynamic color :
            if dynamic is not None:
                col = dynamic_color(col, data)
        elif (data.ndim > 1) and (data.shape[1] == 4):
            col = data.astype(np.float32)
        else:
            col = data
        # else:
        #     raise ValueError("data is not recognized.")

        # Adapt for faces :
        if  col.ndim != 3:
            col = np.transpose(np.tile(col[..., np.newaxis], (1, 1, 3)), (0, 2, 1))
        # else:
        #     col = data

        self._colFaces = np.ascontiguousarray(col, dtype=np.float32)
        self.mesh_color_changed()


    def set_alpha(self, alpha, index=None):
        """Set transparency to the brain

        Args:
            alpha: float
                Transparency
        """
        if index is None:
            index = np.ones((len(self), 3), dtype=np.bool)
        self._colFaces[index, 3] = np.float32(alpha)
        self.mesh_color_changed()


    def set_light(self, l_position=None, l_color=None, l_intensity=None,
                  l_coefAmbient=None, l_coefSpecular=None):
        """Set light properties

        l_position: tuple, optional, (def: (1., 1., 1.))
            Position of the light

        l_color: tuple, optional, (def: (1., 1., 1., 1.))
            Color of the light (RGBA)

        l_intensity: tuple, optional, (def: (1., 1., 1.))
            Intensity of the light

        l_coefAmbient: float, optional, (def: 0.11)
            Coefficient for the ambient light

        l_coefSpecular: float, optional, (def: 0.5)
            Coefficient for the specular light
        """
        # Get lights :
        if l_position is not None:
            self._l_position = l_position
        if l_color is not None:
            self._l_color = l_color
        if l_coefAmbient is not None:
            self._l_coefAmbient = l_coefAmbient
        if l_coefSpecular is not None:
            self._l_coefSpecular = l_coefSpecular
        if l_intensity is not None:
            self._l_intensity = l_intensity
        self.mesh_light_changed()


    def set_camera(self, camera=None):
        """Set a camera to the mesh

        Args:
            name: type
                description

        Kargs:
            camera: vispy.camera, optional, (def: None)
                Set a camera to the Mesh for light adaptation 

        Return
            name: description
        """
        if camera is not None:
            self._camera = camera
            self._camera_transform = self._camera.transform
            self.update()
        else:
            self._camera, self._camera_transform = None, None


    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    # Update data/color/light/camera
    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    def _update_data(self):
        """Update faces/vertices/normals only
        """
        # Define buffers
        self._faces.set_data(self._tri, convert=True)
        self._colors.set_data(self._colFaces, convert=True)
        self._vertices.set_data(self._vertFaces, convert=True)
        self._normals.set_data(self._normFaces, convert=True)

        # Mesh data :
        self.shared_program.vert['a_position'] = self._vertices
        self.shared_program.vert['a_color'] = self._colors
        self.shared_program.vert['a_normal'] = self._normals
        self._data_changed = False

    def _update_color(self):
        """Update color only
        """
        self._colors.set_data(self._colFaces.astype(np.float32))
        self.shared_program.vert['a_color'] = self._colors
        self._color_changed = False

    def _update_light(self):
        """Update light only
        """
        # Define colors and light :
        self.shared_program.vert['u_color'] = self._l_color
        self.shared_program.frag['u_coefAmbient'] = self._l_coefAmbient
        self.shared_program.frag['u_light_position'] = self._l_position
        self.shared_program.frag['u_light_intensity'] = self._l_intensity
        self.shared_program.frag['u_coefSpecular'] = self._l_coefSpecular
        self._light_changed = False


    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    # Properties
    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    @property
    def get_vertices(self):
        """Mesh data"""
        return self._vertFaces

    @property
    def get_normals(self):
        """Normals"""
        return self._normFaces

    @property
    def get_color(self):
        """Vertex color"""
        return self._colFaces

    @property
    def get_l_position(self):
        """Light position"""
        return self._l_position

    @property
    def get_l_intensity(self):
        """Light intensity"""
        return self._l_intensity

    @property
    def get_l_color(self):
        """Light color"""
        return self._l_color

    @property
    def get_l_coef(self):
        """Light coefficients"""
        return tuple([self._l_coefAmbient, self._l_coefSpecular])

    @property
    def get_light(self):
        """List of all light properties"""
        return [*self.get_l_position] + [*self.get_l_intensity] + [*self.get_l_color] + [*self.get_l_coef]

    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    # Drawing functions
    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    def draw(self, *args, **kwds):
        """This is call when drawing only
        """
        Visual.draw(self, *args, **kwds)


    def _prepare_draw(self, view=None):
        """This is call everytime there is an interaction with the mesh
        """
        # Need data update :
        if self._data_changed:
            if self._update_data() is False:
                return False
            self._data_changed = False
        # Need color update :
        if self._color_changed:
            if self._update_color() is False:
                return False
            self._color_changed = False
        # Need light update :
        if self._light_changed:
            if self._update_light() is False:
                return False
            self._light_changed = False
        view_frag = view.view_program.frag
        view_frag['u_light_position'] = self._camera_transform.map(self._l_position)[0:-1]


    @staticmethod
    def _prepare_transforms(view):
        """This is call for the first rendering
        """
        tr = view.transforms
        transform = tr.get_transform()

        view_vert = view.view_program.vert
        view_vert['transform'] = transform


    def projection(self, projection):
        """Switch between internal/external rendering

        Args:
            projection: string
                Use 'internal' or external
        """
        l_color = list(self.get_l_color)
        if projection == 'internal':
            self.set_gl_state('translucent', depth_test=False, cull_face=False)
            l_color[3] = 0.1
            # self.set_gl_state('translucent', depth_test=False, cull_face=True, blend=True,
                              # blend_func=('src_alpha', 'one_minus_src_alpha'))
        else:
            self.set_gl_state('translucent', depth_test=True, cull_face=False)
            l_color[3] = 1
            # self.set_gl_state('translucent', depth_test=True, cull_face=False, blend=True,
                              # blend_func=('src_alpha', 'one_minus_src_alpha'))
        self.set_light(l_color=l_color)
        self.update_gl_state()