"""Help tab content."""

from __future__ import annotations

from maya_agent import __app_name__, __version__
from maya_agent.i18n import get_language, list_languages, t
from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets


def _feature_counts() -> tuple:
    """(tools, categories, providers, languages) for the intro meta line."""
    tools = categories = providers = languages = 0
    try:
        from maya_agent.tools.registry import all_tools, ensure_tools_loaded

        ensure_tools_loaded()
        items = all_tools()
        tools = len(items)
        categories = len({item.category for item in items})
    except Exception:
        pass
    try:
        from maya_agent.llm.registry import list_providers

        providers = len(list_providers())
    except Exception:
        pass
    try:
        languages = len(list_languages())
    except Exception:
        pass
    return tools, categories, providers, languages


def _category_counts() -> dict:
    """Tool count per category (used for the tool inventory headers)."""
    try:
        from maya_agent.tools.registry import all_tools, ensure_tools_loaded

        ensure_tools_loaded()
        counts = {}
        for item in all_tools():
            counts[item.category] = counts.get(item.category, 0) + 1
        return counts
    except Exception:
        return {}


def create_help_panel(parent=None):
    """Top-level help page (same visual language as settings sections)."""
    def _scroll_page():
        page = QtWidgets.QWidget()
        page.setObjectName("settingsPage")
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        root = QtWidgets.QVBoxLayout(page)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        root.setAlignment(QtCore.Qt.AlignTop)
        return scroll, root

    def _section(title: str, hint: str = ""):
        box = QtWidgets.QFrame()
        box.setObjectName("settingsSection")
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(10)
        head = QtWidgets.QVBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(3)
        title_lbl = QtWidgets.QLabel(title)
        title_lbl.setObjectName("settingsSectionTitle")
        title_lbl.setWordWrap(True)
        head.addWidget(title_lbl)
        if hint:
            hint_lbl = QtWidgets.QLabel(hint)
            hint_lbl.setObjectName("settingsSectionHint")
            hint_lbl.setWordWrap(True)
            head.addWidget(hint_lbl)
        lay.addLayout(head)
        return box, lay

    def _add_help_lines(layout, lines, *, numbered: bool = False) -> None:
        for i, line in enumerate(lines, start=1):
            prefix = f"{i}.  " if numbered else "·  "
            row = QtWidgets.QLabel(f"{prefix}{line}")
            row.setObjectName("settingsHelpItem")
            row.setWordWrap(True)
            layout.addWidget(row)

    def _add_note(layout, text: str) -> None:
        row = QtWidgets.QLabel(f"·  {text}")
        row.setObjectName("settingsHelpItem")
        row.setWordWrap(True)
        layout.addWidget(row)

    scroll, root = _scroll_page()

    tools_total, categories_total, providers_total, languages_total = _feature_counts()

    intro = QtWidgets.QFrame()
    intro.setObjectName("settingsSection")
    intro_lay = QtWidgets.QVBoxLayout(intro)
    intro_lay.setContentsMargins(14, 14, 14, 14)
    intro_lay.setSpacing(8)

    title_row = QtWidgets.QHBoxLayout()
    title_row.setSpacing(10)
    title = QtWidgets.QLabel(__app_name__)
    title.setObjectName("settingsHelpTitle")
    ver = QtWidgets.QLabel(f"v{__version__}")
    ver.setObjectName("settingsHelpVersion")
    title_row.addWidget(title, 0)
    title_row.addWidget(ver, 0)
    title_row.addStretch(1)
    intro_lay.addLayout(title_row)

    if tools_total:
        meta = QtWidgets.QLabel(
            t(
                "help.meta",
                tools=tools_total,
                categories=categories_total,
                providers=providers_total,
                languages=languages_total,
            )
        )
        meta.setObjectName("settingsSectionHint")
        meta.setWordWrap(True)
        intro_lay.addWidget(meta)

    blurb = QtWidgets.QLabel(t("help.blurb"))
    blurb.setObjectName("settingsHelpBody")
    blurb.setWordWrap(True)
    intro_lay.addWidget(blurb)
    root.addWidget(intro)

    quick, quick_lay = _section(t("help.quick.title"), t("help.quick.hint"))
    _add_help_lines(
        quick_lay,
        (
            t("help.quick.1"),
            t("help.quick.2"),
            t("help.quick.3"),
            t("help.quick.4"),
        ),
        numbered=True,
    )
    root.addWidget(quick)

    chat, chat_lay = _section(t("help.chat.title"), t("help.chat.hint"))
    _add_help_lines(
        chat_lay,
        (
            t("help.chat.1"),
            t("help.chat.2"),
            t("help.chat.3"),
            t("help.chat.4"),
            t("help.chat.5"),
            t("help.chat.6"),
            t("help.chat.7"),
            t("help.chat.8"),
            t("help.chat.9"),
            t("help.chat.10"),
            t("help.chat.11"),
        ),
    )
    root.addWidget(chat)

    settings, settings_lay = _section(
        t("help.settings.title"), t("help.settings.hint")
    )
    _add_help_lines(
        settings_lay,
        (
            t("help.settings.1"),
            t("help.settings.2"),
            t("help.settings.5"),
            t("help.settings.meshy"),
            t("help.settings.tripo"),
            t("help.settings.hunyuan"),
            t("help.settings.3"),
            t("help.settings.4"),
        ),
    )
    root.addWidget(settings)

    ui_help, ui_help_lay = _section(t("help.ui.title"), t("help.ui.hint"))
    _add_help_lines(
        ui_help_lay,
        (
            t("help.ui.1"),
            t("help.ui.2"),
            t("help.ui.3"),
            t("help.ui.4"),
            t("help.ui.5"),
        ),
    )
    root.addWidget(ui_help)

    mcp, mcp_lay = _section(t("help.mcp.title"), t("help.mcp.hint"))
    _add_help_lines(
        mcp_lay,
        (
            t("help.mcp.1"),
            t("help.mcp.2"),
            t("help.mcp.3"),
            t("help.mcp.4"),
            t("help.mcp.5"),
            t("help.mcp.6"),
        ),
    )
    root.addWidget(mcp)

    tools_title = t("help.tools.title")
    if tools_total:
        tools_title = f"{tools_title}  ({tools_total} / {categories_total})"
    tools, tools_lay = _section(
        tools_title,
        t("help.tools.hint", tools=tools_total, categories=categories_total),
    )
    counts = _category_counts()
    tool_groups = (
        (
            "scene",
            "help.tools.cat.scene",
            "get_scene_info（对象计数 / 全场景 bbox / 相机裁剪 / 材质分布）、"
            "list_selection、select_objects、rename_object、batch_rename、"
            "create_group、parent_objects、duplicate_objects、delete_objects、clean_scene、"
            "set_frame_range、capture_viewport（单视角，可 look_at / show_only）、"
            "capture_viewport_views（多视角，临时相机自动清理）、render_still（静帧展示图）",
        ),
        (
            "modeling",
            "help.tools.cat.modeling",
            "create_primitive（12 种图元）、create_primitives（批量）、"
            "arrange_objects（stack / align / grid / radial）、combine_meshes、separate_meshes、"
            "boolean_meshes、extrude_faces、extrude_edges、bevel_edges、smooth_mesh、reduce_mesh、"
            "mirror_geometry、center_pivot、freeze_transform、"
            "select_mesh_components（按法线 / 索引 / 边界选面边点）、edit_mesh_topology、"
            "edit_mesh_normals、transform_components、create_curve、mesh_from_curve、"
            "create_text_mesh、thicken_mesh、cleanup_mesh、get_mesh_stats、"
            "check_meshes（非流形 / lamina / 零面积 / 硬边占比）",
        ),
        (
            "uv",
            "help.tools.cat.uv",
            "预检：preflight_uv；一键：prepare_game_uv（默认 cut_mode=auto，含清理与 Layout 重试）。"
            "拆分：cut_uv_edges、sew_uv_edges、get_uv_info；"
            "展开：auto_unwrap_uv、unfold_uv、optimize_uv；"
            "排布/密度：layout_uv（支持 UDIM）、set_texel_density；"
            "质检：check_uv_quality（旧名 check_uv_overlaps 已转发）；截图：capture_uv_layout",
        ),
        (
            "rigging",
            "help.tools.cat.rigging",
            "15 个 create_skeleton_* 模板（biped / biped_game / biped_bendy / ue4 / ue5 / previs / "
            "cat / horse / gorilla / bird / fish / bug / dinosaur / dragon / vehicle），"
            "另有 list_skeleton_templates；一键 auto_rig_character（模板 → SkinCage → 蒙皮 → FK/IK）、"
            "auto_rig_biped；关节 create_joint / create_joint_chain / orient_joints；"
            "绑定 bind_skin / unbind_skin；控制器 build_fk_ik_controls / auto_create_fk_controls；"
            "SkinCage create_skin_cage / bind_from_skin_cage；"
            "权重 get_skin_weights / set_skin_weights / analyze / prune / normalize / "
            "limit_skin_influences / mirror / smooth / align_skinned_rig / copy / transfer_skin_weights；"
            "拆皮烘焙 bake_mesh_to_world / delete_mesh_history / clean_rig_nodes / "
            "extract_skinned_geometry / list_skinned_meshes",
        ),
        (
            "adv",
            "help.tools.cat.adv",
            "已安装 ADV 时自动启用：adv_rig_status、adv_auto_rig（一键）、adv_next_step（分步）、"
            "adv_import_fit_skeleton、adv_set_skin_meshes、adv_auto_place_fit、adv_build_rig、"
            "adv_bind_skin、adv_create_controller、adv_list_fit_templates。"
            "路径在「设置」页的 AdvancedSkeleton 栏配置，出厂默认不启用",
        ),
        (
            "animation",
            "help.tools.cat.animation",
            "set_keyframe、delete_keyframes、bake_animation、playblast、copy_animation",
        ),
        (
            "materials",
            "help.tools.cat.materials",
            "create_material（返回 shader + shading_group）、assign_material、assign_texture、"
            "describe_material_attrs、list_materials",
        ),
        (
            "lighting",
            "help.tools.cat.lighting",
            "create_light、create_three_point_lighting、create_environment_light（环境光 / 天光）",
        ),
        (
            "export",
            "help.tools.cat.export",
            "export_fbx（可嵌入贴图）、import_fbx、export_obj、export_usd、export_abc、"
            "save_scene、open_scene",
        ),
        (
            "utilities",
            "help.tools.cat.utilities",
            "set_transform、create_lod_group、create_collision_mesh（UCX_）、"
            "apply_game_naming、reset_transform",
        ),
        (
            "files",
            "help.tools.cat.files",
            "get_workspace_info、list_directory、path_info、read_text_file、write_text_file、"
            "copy_file、delete_path、list_chat_images、save_chat_images、list_chat_files"
            "（读写受白名单限制：工作区 / 临时目录 / Maya 用户目录；对话附件自动落盘到 "
            "chat_images 与 chat_files）",
        ),
        (
            "analysis",
            "help.tools.cat.analysis",
            "generate_chart：折线 / 柱状 / 箱线 / 散点 / 直方 / 饼图，产物自动嵌入回复正文",
        ),
        (
            "web",
            "help.tools.cat.web",
            "web_search、fetch_webpage（正文提取 + 分页续读）、search_images、fetch_image、"
            "fetch_images（无需搜索 API Key；仅公网 http/https 并拦截内网地址；"
            "fetch_image* 仅视觉模型可用）",
        ),
        (
            "meshy",
            "help.tools.cat.meshy",
            "meshy_text_to_3d（preview→refine）、meshy_image_to_3d（可复用对话附图）、"
            "meshy_multi_image_to_3d、meshy_retexture、meshy_remesh、meshy_convert、meshy_resize、"
            "meshy_uv_unwrap、meshy_rig、meshy_animate、meshy_list_animations、meshy_get_task、"
            "meshy_wait_task、meshy_download_model、meshy_import_to_maya、meshy_balance"
            "（需在设置中配置 Meshy API Key；绑定/转换链路要求 FBX 嵌入贴图，导入优先 FBX）",
        ),
        (
            "tripo",
            "help.tools.cat.tripo",
            "文/图/多视图生模型：tripo_text_to_model、tripo_image_to_model、tripo_multiview_to_model；"
            "图像链路：tripo_text_to_image、tripo_image_to_image、tripo_image_to_multiview、"
            "tripo_edit_multiview；后处理：tripo_texture、tripo_convert、tripo_mesh_segment、"
            "tripo_mesh_complete、tripo_mesh_decimate；绑骨动画：tripo_rig_check、tripo_rig、"
            "tripo_retarget、tripo_list_animations；生命周期：tripo_upload_file、tripo_get_task、"
            "tripo_wait_task、tripo_list_tasks、tripo_download、tripo_import_to_maya、"
            "tripo_balance、tripo_usage；Maya 侧安全应用：tripo_prepare_rig_export、"
            "tripo_apply_to_meshes、tripo_apply_animation（需配置 Tripo API Key）",
        ),
        (
            "hunyuan",
            "help.tools.cat.hunyuan",
            "hunyuan_text_to_3d_pro / hunyuan_image_to_3d_pro / hunyuan_multiview_to_3d_pro、"
            "hunyuan_text_to_3d_rapid / hunyuan_image_to_3d_rapid、hunyuan_profile_to_3d / "
            "hunyuan_list_profile_templates、hunyuan_texture / hunyuan_reduce_face / hunyuan_part / "
            "hunyuan_uv、hunyuan_auto_rig / hunyuan_list_motions / hunyuan_motion、"
            "hunyuan_get_job / hunyuan_wait_job / hunyuan_convert / hunyuan_download / "
            "hunyuan_import_to_maya、hunyuan_test_connection"
            "（需 SecretId/SecretKey；3D 后处理输入仅公网 file_url 或上游 JobId 串联，"
            "不支持本地网格直传；导入优先 FBX）",
        ),
        (
            "scripting",
            "help.tools.cat.scripting",
            "execute_python（atomic 默认回滚）、execute_mel、generate_python_snippet",
        ),
        (
            "maya_dev",
            "help.tools.cat.maya_dev",
            "环境与 API：get_maya_dev_env、lookup_cmds_help、search_cmds、lookup_api_help、"
            "inspect_node、list_node_types；校验与执行：validate_python、read_script_file、"
            "write_script_file、list_script_files、run_python_file、reload_python_module；"
            "脚手架与 UI：scaffold_maya_tool、create_shelf_button、list_shelves；"
            "插件：list_plugins、load_or_unload_plugin、eval_python_expr",
        ),
    )
    use_zh = str(get_language() or "").startswith("zh")
    _EN_TOOL_DESCS = {
        "scene": ('get_scene_info, list_selection, select_objects, rename_object, batch_rename, create_group, parent_objects, duplicate_objects, delete_objects, clean_scene, set_frame_range, capture_viewport, capture_viewport_views, render_still'),
        "modeling": ('create_primitive, create_primitives, arrange_objects, combine_meshes, separate_meshes, boolean_meshes, extrude_faces, extrude_edges, bevel_edges, smooth_mesh, reduce_mesh, mirror_geometry, center_pivot, freeze_transform, select_mesh_components, edit_mesh_topology, edit_mesh_normals, transform_components, create_curve, mesh_from_curve, create_text_mesh, thicken_mesh, cleanup_mesh, get_mesh_stats, check_meshes'),
        "uv": ('preflight_uv, prepare_game_uv, cut_uv_edges, sew_uv_edges, get_uv_info, auto_unwrap_uv, unfold_uv, optimize_uv, layout_uv, set_texel_density, check_uv_quality, capture_uv_layout'),
        "rigging": ('create_skeleton_* templates, list_skeleton_templates, auto_rig_character, auto_rig_biped, create_joint, create_joint_chain, orient_joints, bind_skin, unbind_skin, build_fk_ik_controls, create_skin_cage, bind_from_skin_cage, skin weight tools, extract_skinned_geometry, list_skinned_meshes'),
        "adv": ('adv_rig_status, adv_auto_rig, adv_next_step, adv_import_fit_skeleton, adv_set_skin_meshes, adv_auto_place_fit, adv_build_rig, adv_bind_skin, adv_create_controller, adv_list_fit_templates (enabled when AdvancedSkeleton is installed)'),
        "animation": ('set_keyframe, delete_keyframes, bake_animation, playblast, copy_animation'),
        "materials": ('create_material, assign_material, assign_texture, describe_material_attrs, list_materials'),
        "lighting": ('create_light, create_three_point_lighting, create_environment_light'),
        "export": ('export_fbx, import_fbx, export_obj, export_usd, export_abc, save_scene, open_scene'),
        "utilities": ('set_transform, create_lod_group, create_collision_mesh, apply_game_naming, reset_transform'),
        "files": ('get_workspace_info, list_directory, path_info, read_text_file, write_text_file, copy_file, delete_path, list_chat_images, save_chat_images, list_chat_files (allowlisted paths: workspace / temp / Maya user dirs)'),
        "analysis": ('generate_chart (line / bar / box / scatter / hist / pie); charts embed in the reply'),
        "web": ('web_search, fetch_webpage, search_images, fetch_image, fetch_images (no search API key; public http/https only; fetch_image* requires vision models)'),
        "meshy": ('meshy_text_to_3d, meshy_image_to_3d, meshy_multi_image_to_3d, meshy_retexture, meshy_remesh, meshy_convert, meshy_resize, meshy_uv_unwrap, meshy_rig, meshy_animate, meshy_list_animations, meshy_get_task, meshy_wait_task, meshy_download_model, meshy_import_to_maya, meshy_balance'),
        "tripo": ('tripo_text_to_model, tripo_image_to_model, tripo_multiview_to_model, tripo_text_to_image, tripo_image_to_image, tripo_image_to_multiview, tripo_edit_multiview, tripo_texture, tripo_convert, tripo_mesh_segment, tripo_mesh_complete, tripo_mesh_decimate, tripo_rig_check, tripo_rig, tripo_retarget, tripo_list_animations, tripo_upload_file, tripo_get_task, tripo_wait_task, tripo_list_tasks, tripo_download, tripo_import_to_maya, tripo_balance, tripo_usage, tripo_prepare_rig_export, tripo_apply_to_meshes, tripo_apply_animation'),
        "hunyuan": ('hunyuan_text_to_3d_pro / image / multiview, rapid variants, profile templates, texture / reduce_face / part / uv, auto_rig / motions, job wait / convert / download / import_to_maya, test_connection (SecretId/SecretKey; public file_url or upstream JobId)'),
        "scripting": ('execute_python (atomic rollback default), execute_mel, generate_python_snippet'),
        "maya_dev": ('get_maya_dev_env, lookup_cmds_help, search_cmds, lookup_api_help, inspect_node, list_node_types, validate_python, read/write/list/run script files, scaffold_maya_tool, create_shelf_button, list_shelves, list_plugins, load_or_unload_plugin, eval_python_expr')
    }
    for category, label_key, names_zh in tool_groups:
        label = t(label_key)
        count = counts.get(category, 0)
        cat_text = f"{label}  [{count}]" if count else label
        cat_lbl = QtWidgets.QLabel(cat_text)
        cat_lbl.setObjectName("settingsHelpCat")
        cat_lbl.setWordWrap(True)
        tools_lay.addWidget(cat_lbl)
        names = names_zh if use_zh else _EN_TOOL_DESCS.get(category, names_zh)
        names_lbl = QtWidgets.QLabel(names)
        names_lbl.setObjectName("settingsHelpItem")
        names_lbl.setWordWrap(True)
        tools_lay.addWidget(names_lbl)

    _add_note(tools_lay, t("help.tools.note_destructive"))
    _add_note(tools_lay, t("help.tools.note_vision"))
    _add_note(tools_lay, t("help.tools.note_threads"))
    root.addWidget(tools)

    rules, rules_lay = _section(t("help.rules.title"), t("help.rules.hint"))
    _add_help_lines(
        rules_lay,
        (
            t("help.rules.1"),
            t("help.rules.2"),
            t("help.rules.3"),
            t("help.rules.4"),
            t("help.rules.5"),
            t("help.rules.6"),
            t("help.rules.7"),
        ),
    )
    root.addWidget(rules)

    more, more_lay = _section(t("help.more.title"), t("help.more.hint"))
    _add_help_lines(
        more_lay,
        (
            t("help.more.1"),
            t("help.more.2"),
            t("help.more.3"),
            t("help.more.4"),
            t("help.more.5"),
            t("help.more.6"),
            t("help.more.7"),
        ),
    )
    root.addWidget(more)

    root.addStretch(1)

    wrap = QtWidgets.QWidget(parent)
    wrap.setObjectName("settingsPanel")
    wrap_lay = QtWidgets.QVBoxLayout(wrap)
    wrap_lay.setContentsMargins(0, 6, 0, 0)
    wrap_lay.setSpacing(0)
    wrap_lay.addWidget(scroll, 1)
    return wrap
