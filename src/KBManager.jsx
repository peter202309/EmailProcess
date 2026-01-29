import React, { useState, useEffect } from 'react';
import { Upload, RefreshCw, History, Trash2, Check, X, Clock, FolderOpen, AlertCircle } from 'lucide-react';

export default function KBManager({ isOpen, onClose }) {
    const [files, setFiles] = useState([]);
    const [selectedFile, setSelectedFile] = useState(null);
    const [fileHistory, setFileHistory] = useState([]);
    const [isScanning, setIsScanning] = useState(false);
    const [isSyncing, setIsSyncing] = useState(false);
    const [changes, setChanges] = useState(null);

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

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="bg-white rounded-xl shadow-2xl w-[90%] max-w-6xl h-[85vh] flex flex-col">
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
                <div className="flex-1 overflow-auto">
                    <table className="w-full">
                        <thead className="bg-gray-50 sticky top-0 border-b">
                            <tr>
                                <th className="text-left p-4 font-bold text-gray-700">文件名</th>
                                <th className="text-left p-4 font-bold text-gray-700">大小</th>
                                <th className="text-left p-4 font-bold text-gray-700">版本</th>
                                <th className="text-left p-4 font-bold text-gray-700">上传时间</th>
                                <th className="text-left p-4 font-bold text-gray-700">最后修改</th>
                                <th className="text-left p-4 font-bold text-gray-700">同步状态</th>
                                <th className="text-left p-4 font-bold text-gray-700">操作</th>
                            </tr>
                        </thead>
                        <tbody>
                            {files.length === 0 ? (
                                <tr>
                                    <td colSpan="7" className="text-center p-8 text-gray-400">
                                        <FolderOpen size={48} className="mx-auto mb-2 opacity-30" />
                                        <p>暂无文件，请上传或扫描知识库目录</p>
                                    </td>
                                </tr>
                            ) : (
                                files.map(file => (
                                    <tr key={file.id} className="border-b hover:bg-gray-50 transition-colors">
                                        <td className="p-4">
                                            <div className="font-medium text-gray-800">{file.filename}</div>
                                            <div className="text-xs text-gray-400">{file.file_path}</div>
                                        </td>
                                        <td className="p-4 text-sm text-gray-600">{formatFileSize(file.file_size)}</td>
                                        <td className="p-4">
                                            <span className="px-2 py-1 bg-blue-100 text-blue-700 rounded text-xs font-bold">
                                                v{file.version}
                                            </span>
                                        </td>
                                        <td className="p-4 text-sm text-gray-600">{formatDate(file.upload_time)}</td>
                                        <td className="p-4 text-sm text-gray-600">{formatDate(file.last_modified)}</td>
                                        <td className="p-4">
                                            <div className="flex items-center gap-2">
                                                {getSyncStatusIcon(file.sync_status)}
                                                <span className="text-xs capitalize">{file.sync_status}</span>
                                            </div>
                                        </td>
                                        <td className="p-4">
                                            <div className="flex gap-2">
                                                <button
                                                    onClick={() => handleViewHistory(file)}
                                                    className="p-2 hover:bg-blue-100 rounded transition-colors"
                                                    title="查看历史"
                                                >
                                                    <History size={16} className="text-blue-600" />
                                                </button>
                                                <button
                                                    onClick={() => handleDelete(file.id, file.filename)}
                                                    className="p-2 hover:bg-red-100 rounded transition-colors"
                                                    title="删除"
                                                >
                                                    <Trash2 size={16} className="text-red-600" />
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>

                {/* Version History Sidebar */}
                {selectedFile && (
                    <div className="absolute right-0 top-0 bottom-0 w-96 bg-white border-l shadow-2xl flex flex-col">
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
