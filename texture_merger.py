bl_info = {
    "name": "灰度图合并",
    "author": "b站：漓舒Mixedshear https://space.bilibili.com/500957923?spm_id_from=333.1007.0.0",
    "version": (1, 5),
    "blender": (3, 6, 0),
    "location": "着色器编辑器 > 侧边栏 > 贴图工具",
    "description": "支持超大图像处理的分块合并工具",
    "warning": "",
    "category": "Material"
}

import bpy
import os
import numpy as np
from bpy.props import (
    StringProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
)
from bpy.types import (
    Operator,
    Panel,
    PropertyGroup,
)

class TextureMergeProperties(PropertyGroup):
    # 通道配置
    channel_r: StringProperty(name="红通道")
    channel_g: StringProperty(name="绿通道")
    channel_b: StringProperty(name="蓝通道")
    channel_a: StringProperty(name="Alpha通道")
    
    # 分块设置
    tile_size: IntProperty(
        name="分块尺寸",
        default=1024,
        min=256,
        max=4096,
        description="处理超大图像时的分块尺寸（像素）"
    )
    
    # 输出配置
    output_name: StringProperty(
        name="输出名称",
        default="Merged_Texture",
    )
    output_type: EnumProperty(
        name="输出类型",
        items=[
            ('RGB', "RGB", "合并为RGB贴图"),
            ('RGBA', "RGBA", "合并为RGBA贴图"),
        ],
        default='RGB'
    )
    output_format: EnumProperty(
        name="输出格式",
        items=[
            ('PNG', "PNG", "PNG格式（8/16位）"),
            ('OPEN_EXR', "EXR", "EXR格式（32位浮点）"),
            ('JPEG', "JPEG", "JPEG格式（8位）"),
            ('TIFF', "TIFF", "TIFF格式（16/32位）"),
        ],
        default='OPEN_EXR'
    )
    output_path: StringProperty(
        name="保存路径",
        subtype='DIR_PATH'
    )

class MERGE_OT_texture(Operator):
    bl_idname = "texture.merge_channels"
    bl_label = "合并通道"
    bl_options = {'REGISTER', 'UNDO'}

    def _process_tile(self, images, merged, tile_x, tile_y, tile_size, width, height, channels_count):
        """处理单个分块区域"""
        # 计算当前分块的边界
        x_start = tile_x * tile_size
        x_end = min((tile_x + 1) * tile_size, width)
        y_start = tile_y * tile_size
        y_end = min((tile_y + 1) * tile_size, height)
        
        # 初始化分块缓冲区
        tile = np.ones((y_end - y_start, x_end - x_start, 4), dtype=np.float32)

        # 处理每个通道
        for channel_idx, channel in enumerate(['R', 'G', 'B', 'A'][:channels_count]):
            if channel not in images:
                continue

            img = images[channel]
            # 读取当前分块数据
            pixels = np.empty(img.size[0] * img.size[1] * img.channels, dtype=np.float32)
            img.pixels.foreach_get(pixels)
            
            # 提取所需通道并重塑为二维数组
            if img.channels > 1:
                channel_data = pixels[::img.channels].reshape(height, width)
            else:
                channel_data = pixels.reshape(height, width)
            
            # 填充到当前分块
            tile[:, :, channel_idx] = channel_data[y_start:y_end, x_start:x_end]

        # 将处理好的分块写回目标图像
        merged[y_start:y_end, x_start:x_end, :] = tile

    def execute(self, context):
        props = context.scene.texture_merge_props
        tile_size = props.tile_size
        
        # 收集输入图像
        images = {}
        for channel in ['R', 'G', 'B', 'A']:
            if img_name := getattr(props, f"channel_{channel.lower()}").strip():
                if not (img := bpy.data.images.get(img_name)):
                    self.report({'ERROR'}, f"找不到图像: {img_name}")
                    return {'CANCELLED'}
                images[channel] = img

        if not images:
            self.report({'ERROR'}, "至少需要选择一个输入通道")
            return {'CANCELLED'}

        # 验证尺寸
        sizes = {img.size[:] for img in images.values()}
        if len(sizes) > 1:
            self.report({'ERROR'}, "所有贴图必须具有相同的尺寸")
            return {'CANCELLED'}
        width, height = sizes.pop()

        # 初始化合并图像
        channels_count = 4 if props.output_type == 'RGBA' else 3
        merged = np.ones((height, width, 4), dtype=np.float32)

        # 计算分块数量
        x_tiles = (width + tile_size - 1) // tile_size
        y_tiles = (height + tile_size - 1) // tile_size
        total_tiles = x_tiles * y_tiles
        processed_tiles = 0

        # 初始化进度条
        wm = context.window_manager
        wm.progress_begin(0, total_tiles)

        try:
            # 分块处理
            for y in range(y_tiles):
                for x in range(x_tiles):
                    self._process_tile(images, merged, x, y, tile_size, width, height, channels_count)
                    processed_tiles += 1
                    wm.progress_update(processed_tiles)
                    
                    # 每处理10个分块更新一次界面
                    if processed_tiles % 10 == 0:
                        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
        finally:
            wm.progress_end()

        # 创建输出图像
        merged_image = bpy.data.images.new(
            name=props.output_name,
            width=width,
            height=height,
            alpha=(channels_count == 4),
            float_buffer=(props.output_format == 'OPEN_EXR')
        )

        # 高效写入数据
        merged_image.pixels.foreach_set(merged.ravel())
        merged_image.pack()

        # 保存文件
        if props.output_path:
            output_dir = bpy.path.abspath(props.output_path)
            os.makedirs(output_dir, exist_ok=True)
            
            format_settings = {
                'PNG': '.png',
                'OPEN_EXR': '.exr',
                'JPEG': '.jpg',
                'TIFF': '.tif'
            }
            ext = format_settings.get(props.output_format, '.exr')
            merged_image.file_format = props.output_format
            merged_image.save_render(os.path.join(output_dir, f"{props.output_name}{ext}"))

        self.report({'INFO'}, f"合并完成: {merged_image.name}")
        return {'FINISHED'}

class TEXTUREMERGE_PT_Panel(Panel):
    bl_label = "贴图合并"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "灰度图合并器"

    def draw(self, context):
        layout = self.layout
        props = context.scene.texture_merge_props

        # 分块设置
        box = layout.box()
        box.label(text="高级设置:")
        box.prop(props, "tile_size")
        
        # 输出配置
        layout.prop(props, "output_type", expand=True)
        layout.prop(props, "output_format")
        
        # 通道选择
        box = layout.box()
        box.prop_search(props, "channel_r", bpy.data, "images", text="红通道")
        box.prop_search(props, "channel_g", bpy.data, "images", text="绿通道")
        box.prop_search(props, "channel_b", bpy.data, "images", text="蓝通道")
        if props.output_type == 'RGBA':
            box.prop_search(props, "channel_a", bpy.data, "images", text="Alpha通道")

        # 输出设置
        layout.prop(props, "output_name")
        layout.prop(props, "output_path")
        layout.operator("texture.merge_channels")

classes = (
    TextureMergeProperties,
    MERGE_OT_texture,
    TEXTUREMERGE_PT_Panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.texture_merge_props = PointerProperty(type=TextureMergeProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.texture_merge_props

if __name__ == "__main__":
    register()