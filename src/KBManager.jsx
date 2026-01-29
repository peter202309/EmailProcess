import React, { useState, useEffect } from 'react';
import { Upload, RefreshCw, History, Trash2, Check, X, Clock, FolderOpen, AlertCircle, Edit, FileText } from 'lucide-react';

export default function KBManager({ isOpen, onClose }) {
    const [files, setFiles] = useState([]);
    const [selectedFile, setSelectedFile] = useState(null);
    const [fileHistory, setFileHistory] = useState([]);
    const [isScanning, setIsScanning] = useState(false);
    const [isSyncing, setIsSyncing] = useState(false);
    const [changes, setChanges] = useState(null);

    const [editingFile, setEditingFile] = useState(null); // File being edited
    const [editForm, setEditForm] = useState({ category: '', expiry_date: '' });
    const [showExpiredOnly, setShowExpiredOnly] = useState(false);

    // Categories preset
    const CATEGORIES = ["长期 (Long-term)", "短期 (Short-term)", "合同 (Contract)", "参考 (Reference)", "其他 (Other)"];

    useEffect(() => {
        if (isOpen) {
            fetchFiles();
        }
    }, [isOpen]);

    const fetchFiles = async () => {
        try {
            const res = await fetch('http://localhost:8010/kb-files');
            const data = await res.json();
            setFiles(data);
        } catch (error) {
            console.error('Failed to fetch files:', error);
        }
    };

    const handleScan = async () => {
        setIsScanning(true);
        try {
            const res = await fetch('http://localhost:8010/kb-files/scan', { method: 'POST' });
            const data = await res.json();
            setChanges(data.changes);
        } catch (error) {
            console.error('Scan failed:', error);
        } finally {
            setIsScanning(false);
        }
    };

    const handleSync = async () => {
        setIsSyncing(true);
        try {
            const res = await fetch('http://localhost:8010/kb-files/sync', { method: 'POST' });
            const data = await res.json();
            alert(data.message || '同步完成！');
            setChanges(null);
            fetchFiles();
        } catch (error) {
            console.error('Sync failed:', error);
            alert('同步失败');
        } finally {
            setIsSyncing(false);
        }
    };

    const handleUpload = async (event) => {
        const file = event.target.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('http://localhost:8010/kb-files/upload', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (data.status === 'success') {
                alert(`文件上传成功: ${data.filename}`);
                fetchFiles();
            } else {
                alert(`上传失败: ${data.detail}`);
            }
        } catch (error) {
            console.error('Upload failed:', error);
            alert('上传失败');
        }
    };

    const handleDelete = async (fileId, filename) => {
        if (!confirm(`确定要删除 "${filename}" 吗？`)) return;

        try {
            const res = await fetch(`http://localhost:8010/kb-files/${fileId}`, { method: 'DELETE' });
            const data = await res.json();
            if (data.status === 'success') {
                alert('文件已删除');
                fetchFiles();
            }
        } catch (error) {
            console.error('Delete failed:', error);
            alert('删除失败');
        }
    };

    const handleViewHistory = async (file) => {
        setSelectedFile(file);
        try {
            const res = await fetch(`http://localhost:8010/kb-files/${file.id}/history`);
            const data = await res.json();
            setFileHistory(data.history || []);
        } catch (error) {
            console.error('Failed to fetch history:', error);
        }
    };

    const getSyncStatusIcon = (status) => {
        switch (status) {
            case 'synced': return <Check className="text-green-500" size={16} />;
            case 'pending': return <Clock className="text-yellow-500" size={16} />;
            case 'failed': return <X className="text-red-500" size={16} />;
            default: return <RefreshCw className="text-gray-400" size={16} />;
        }
    };

    const formatFileSize = (bytes) => {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    };

    const formatDate = (dateStr) => {
        if (!dateStr) return '-';
        return new Date(dateStr).toLocaleString('zh-CN');
    };

    const handleEditClick = (file) => {
        setEditingFile(file);
        setEditForm({
            category: file.category || '',
            expiry_date: file.expiry_date || ''
        });
    };

    const handleSaveEdit = async () => {
        if (!editingFile) return;

        try {
            const res = await fetch(`http://localhost:8010/kb-files/${editingFile.id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(editForm)
            });
            const data = await res.json();
            if (data.status === 'success') {
                alert('更新成功');
                setEditingFile(null);
                fetchFiles();
            } else {
                alert('更新失败: ' + data.message);
            }
        } catch (e) {
            alert('网络错误');
        }
    };

    const isExpired = (dateStr) => {
        if (!dateStr) return false;
        const today = new Date().toISOString().split('T')[0];
        return dateStr < today;
    };

    const isExpiringSoon = (dateStr) => {
        if (!dateStr) return false;
        if (isExpired(dateStr)) return false; // Already expired
        const today = new Date();
        const expiry = new Date(dateStr);
        const diffTime = Math.abs(expiry - today);
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        return diffDays <= 7; // 7 days warning
    };

    const filteredFiles = files.filter(f => {
        if (showExpiredOnly) {
            return isExpired(f.expiry_date);
        }
        return true;
    });

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="bg-white rounded-xl shadow-2xl w-[95%] max-w-7xl h-[90vh] flex flex-col">
                {/* Header */}
                <div className="p-6 border-b bg-gradient-to-r from-purple-50 to-indigo-50">
                    <div className="flex justify-between items-center mb-4">
                        <div className="flex items-center gap-3">
                            <FolderOpen className="text-purple-600" size={28} />
                            <h2 className="text-2xl font-bold text-gray-800">知识库文件管理</h2>
                        </div>
                        <button onClick={onClose} className="px-4 py-2 border rounded-lg hover:bg-gray-100 transition-colors">
                            关闭
                        </button>
                    </div>

                    <div className="flex justify-between items-center">
                        <div className="flex gap-3">
                            <button
                                onClick={handleScan}
                                disabled={isScanning}
                                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2 transition-colors disabled:opacity-50"
                            >
                                <RefreshCw size={16} className={isScanning ? 'animate-spin' : ''} />
                                {isScanning ? '扫描中...' : '扫描变更'}
                            </button>

                            {changes && (
                                <button
                                    onClick={handleSync}
                                    disabled={isSyncing}
                                    className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 flex items-center gap-2 transition-colors disabled:opacity-50 animate-pulse"
                                >
                                    <AlertCircle size={16} />
                                    {isSyncing ? '同步中...' : `同步变更 (${changes.summary.new_count + changes.summary.modified_count + changes.summary.deleted_count})`}
                                </button>
                            )}

                            <label className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 cursor-pointer flex items-center gap-2 transition-colors">
                                <Upload size={16} />
                                上传文件
                                <input type="file" className="hidden" onChange={handleUpload} />
                            </label>
                        </div>

                        <div className="flex items-center gap-2">
                            <label className="flex items-center gap-2 cursor-pointer select-none px-3 py-2 border rounded-lg bg-white hover:bg-red-50 border-red-200">
                                <input
                                    type="checkbox"
                                    checked={showExpiredOnly}
                                    onChange={(e) => setShowExpiredOnly(e.target.checked)}
                                    className="w-4 h-4 text-red-600 rounded focus:ring-red-500"
                                />
                                <span className={`text-sm font-bold ${showExpiredOnly ? 'text-red-600' : 'text-gray-600'}`}>
                                    只显示已过期
                                </span>
                            </label>
                        </div>
                    </div>
                </div>

                {/* Changes Summary */}
                {changes && (
                    <div className="px-6 py-3 bg-yellow-50 border-b border-yellow-200">
                        <div className="flex items-center gap-4 text-sm">
                            <span className="font-bold text-yellow-800">检测到变更:</span>
                            {changes.summary.new_count > 0 && (
                                <span className="text-green-700">新增 {changes.summary.new_count} 个</span>
                            )}
                            {changes.summary.modified_count > 0 && (
                                <span className="text-blue-700">修改 {changes.summary.modified_count} 个</span>
                            )}
                            {changes.summary.deleted_count > 0 && (
                                <span className="text-red-700">删除 {changes.summary.deleted_count} 个</span>
                            )}
                        </div>
                    </div>
                )}

                {/* File List */}
                <div className="flex-1 overflow-auto bg-gray-50/50">
                    <table className="w-full">
                        <thead className="bg-gray-50 sticky top-0 border-b shadow-sm z-10">
                            <tr>
                                <th className="text-left p-4 font-bold text-gray-700">文件名</th>
                                <th className="text-left p-4 font-bold text-gray-700 w-32">分类</th>
                                <th className="text-left p-4 font-bold text-gray-700 w-32">有效期</th>
                                <th className="text-left p-4 font-bold text-gray-700">状态</th>
                                <th className="text-left p-4 font-bold text-gray-700 w-24">版本</th>
                                <th className="text-left p-4 font-bold text-gray-700">上传时间</th>
                                <th className="text-left p-4 font-bold text-gray-700 text-right">操作</th>
                            </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-100">
                            {filteredFiles.length === 0 ? (
                                <tr>
                                    <td colSpan="7" className="text-center p-12 text-gray-400">
                                        <FolderOpen size={48} className="mx-auto mb-4 opacity-30" />
                                        <p className="text-lg">暂无文件</p>
                                        <p className="text-sm opacity-70">请上传或扫描知识库目录</p>
                                    </td>
                                </tr>
                            ) : (
                                filteredFiles.map(file => {
                                    const expired = isExpired(file.expiry_date);
                                    const expiring = isExpiringSoon(file.expiry_date);

                                    return (
                                        <tr key={file.id} className={`hover:bg-blue-50/50 transition-colors ${expired ? 'bg-red-50/30' : ''}`}>
                                            <td className="p-4">
                                                <div className="flex items-center gap-3">
                                                    <div className="p-2 bg-gray-100 rounded-lg text-gray-500">
                                                        <FileText size={20} />
                                                    </div>
                                                    <div>
                                                        <div className={`font-semibold ${expired ? 'text-red-700' : 'text-gray-800'}`}>
                                                            {file.filename}
                                                        </div>
                                                        <div className="text-xs text-gray-400">{file.file_path} • {formatFileSize(file.file_size)}</div>
                                                    </div>
                                                </div>
                                            </td>
                                            <td className="p-4">
                                                {file.category ? (
                                                    <span className="px-2 py-1 bg-indigo-50 text-indigo-700 rounded-md text-xs font-bold border border-indigo-100">
                                                        {file.category}
                                                    </span>
                                                ) : (
                                                    <span className="text-gray-300 text-xs">-</span>
                                                )}
                                            </td>
                                            <td className="p-4">
                                                {file.expiry_date ? (
                                                    <div className="flex items-center gap-2">
                                                        <span className={`text-sm font-medium ${expired ? 'text-red-600' : expiring ? 'text-orange-500' : 'text-gray-600'}`}>
                                                            {file.expiry_date}
                                                        </span>
                                                        {expired && <span className="bg-red-100 text-red-600 text-[10px] px-1.5 py-0.5 rounded font-bold">已过期</span>}
                                                        {expiring && <span className="bg-orange-100 text-orange-600 text-[10px] px-1.5 py-0.5 rounded font-bold">即将过期</span>}
                                                    </div>
                                                ) : (
                                                    <span className="text-gray-300 text-xs">-</span>
                                                )}
                                            </td>
                                            <td className="p-4">
                                                <div className="flex items-center gap-2" title={file.sync_status}>
                                                    {getSyncStatusIcon(file.sync_status)}
                                                    <span className="text-xs capitalize text-gray-600">{file.sync_status === 'synced' ? '已同步' : file.sync_status}</span>
                                                </div>
                                            </td>
                                            <td className="p-4">
                                                <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs font-mono">
                                                    v{file.version}
                                                </span>
                                            </td>
                                            <td className="p-4 text-sm text-gray-500">
                                                {formatDate(file.upload_time).split(' ')[0]}
                                            </td>
                                            <td className="p-4 text-right">
                                                <div className="flex justify-end gap-1">
                                                    <button
                                                        onClick={() => handleEditClick(file)}
                                                        className="p-2 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-all"
                                                        title="设置分类与有效期"
                                                    >
                                                        <Edit size={16} />
                                                    </button>
                                                    <button
                                                        onClick={() => handleViewHistory(file)}
                                                        className="p-2 text-gray-500 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-all"
                                                        title="查看历史"
                                                    >
                                                        <History size={16} />
                                                    </button>
                                                    <button
                                                        onClick={() => handleDelete(file.id, file.filename)}
                                                        className="p-2 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
                                                        title="删除"
                                                    >
                                                        <Trash2 size={16} />
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })
                            )}
                        </tbody>
                    </table>
                </div>

                {/* Editing Modal */}
                {editingFile && (
                    <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4">
                        <div className="bg-white rounded-xl shadow-2xl w-full max-w-md overflow-hidden transform transition-all scale-100">
                            <div className="p-4 border-b bg-gray-50 flex justify-between items-center">
                                <h3 className="font-bold text-gray-800">编辑文件属性</h3>
                                <button onClick={() => setEditingFile(null)} className="text-gray-400 hover:text-gray-600">
                                    <X size={20} />
                                </button>
                            </div>
                            <div className="p-6 space-y-4">
                                <div>
                                    <label className="block text-sm font-semibold text-gray-700 mb-1">文件名</label>
                                    <div className="text-gray-600 text-sm bg-gray-50 p-2 rounded border">{editingFile.filename}</div>
                                </div>

                                <div>
                                    <label className="block text-sm font-semibold text-gray-700 mb-1">分类 (Category)</label>
                                    <select
                                        className="w-full p-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                                        value={editForm.category}
                                        onChange={(e) => setEditForm({ ...editForm, category: e.target.value })}
                                    >
                                        <option value="">(无分类)</option>
                                        {CATEGORIES.map(c => (
                                            <option key={c} value={c.split(' ')[0]}>{c}</option>
                                        ))}
                                    </select>
                                </div>

                                <div>
                                    <label className="block text-sm font-semibold text-gray-700 mb-1">有效期 (Expiry Date)</label>
                                    <input
                                        type="date"
                                        className="w-full p-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                                        value={editForm.expiry_date}
                                        onChange={(e) => setEditForm({ ...editForm, expiry_date: e.target.value })}
                                    />
                                    <p className="text-xs text-gray-400 mt-1">设置日期后，过期文件将会被标红提醒</p>
                                </div>
                            </div>
                            <div className="p-4 border-t bg-gray-50 flex justify-end gap-2">
                                <button onClick={() => setEditingFile(null)} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg">取消</button>
                                <button onClick={handleSaveEdit} className="px-4 py-2 bg-blue-600 text-white hover:bg-blue-700 rounded-lg font-medium">保存更改</button>
                            </div>
                        </div>
                    </div>
                )}

                {/* Version History Sidebar */}
                {selectedFile && (
                    <div className="absolute right-0 top-0 bottom-0 w-96 bg-white border-l shadow-2xl flex flex-col z-[55]">
                        <div className="p-6 border-b bg-gradient-to-r from-blue-50 to-indigo-50">
                            <div className="flex justify-between items-start mb-2">
                                <h3 className="font-bold text-lg">版本历史</h3>
                                <button onClick={() => setSelectedFile(null)} className="text-gray-400 hover:text-gray-600">
                                    <X size={20} />
                                </button>
                            </div>
                            <p className="text-sm text-gray-600 truncate">{selectedFile.filename}</p>
                        </div>

                        <div className="flex-1 overflow-auto p-4">
                            {fileHistory.length === 0 ? (
                                <p className="text-center text-gray-400 mt-8">暂无历史记录</p>
                            ) : (
                                <div className="space-y-3">
                                    {fileHistory.map((version, index) => (
                                        <div key={version.id} className={`p-4 rounded-lg border-2 ${index === 0 ? 'bg-blue-50 border-blue-200' : 'bg-gray-50 border-gray-200'}`}>
                                            <div className="flex justify-between items-center mb-2">
                                                <span className="font-bold text-blue-700">v{version.version}</span>
                                                {index === 0 && <span className="text-xs bg-blue-600 text-white px-2 py-1 rounded">当前</span>}
                                            </div>
                                            <div className="text-xs text-gray-600 space-y-1">
                                                <div>大小: {formatFileSize(version.file_size)}</div>
                                                <div>哈希: {version.file_hash.substring(0, 12)}...</div>
                                                <div>创建: {formatDate(version.created_at)}</div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
