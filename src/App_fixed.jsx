// This is a temporary fixed version - will be used to replace the broken App.jsx
// The EmailRow component at the end of App.jsx was corrupted with misplaced modal code
// This file contains the correct EmailRow component without the broken modal reference

function EmailRow({ email, onClick }) {
    const isUrgent = email.aiAnalysis?.isUrgent;
    const category = email.aiAnalysis?.category || (email.aiAnalysis ? "Information" : null);
    const isUnread = !email.isRead;
    const isProcessed = email.status === 'processed';
    const isPending = !isProcessed;

    // Choose border and background colors based on status
    let statusClasses = 'border-slate-100';
    if (isUrgent) {
        statusClasses = 'border-red-500 bg-red-50/30';
    } else if (isProcessed) {
        statusClasses = 'border-green-500 bg-white opacity-80';
    } else if (isPending) {
        statusClasses = 'border-blue-500 bg-blue-50/5';
    }

    return (
        <div onClick={onClick} className={`p-4 hover:bg-slate-50 cursor-pointer flex justify-between items-center border-l-4 transition-all shadow-sm mb-2 rounded-r-lg ${statusClasses}`}>
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-1">
                    {isUnread && <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />}
                    <div className={`font-bold text-sm truncate ${isUrgent ? 'text-red-700 underline decoration-red-200 decoration-2 underline-offset-4' : ''} ${isUnread ? 'font-extrabold' : ''}`}>
                        {email.subject}
                    </div>
                    {isUrgent && <span className="px-1.5 py-0.5 bg-red-600 text-white text-[8px] font-bold rounded animate-pulse shadow-sm">CRITICAL</span>}
                    {email.sentReply && <span className="px-1.5 py-0.5 bg-green-50 text-green-600 text-[8px] font-bold rounded border border-green-100">REPLIED</span>}
                </div>
                <div className="flex items-center gap-3">
                    {category && (
                        <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold border uppercase ${getCategoryStyles(category)}`}>
                            {category}
                        </span>
                    )}
                    <div className="text-xs text-slate-500 font-medium truncate">{email.from}</div>
                    {email.accountOwner && (
                        <span className="text-[9px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200">
                            @{email.accountOwner.split('@')[0]}
                        </span>
                    )}
                    <div className="text-[9px] text-slate-400 font-mono ml-auto">{email.receivedAt}</div>
                </div>
            </div>
            <div className="text-[10px] text-slate-400 ml-4 font-mono font-bold">{email.receivedAt?.split(' ')[1]}</div>
        </div>
    );
}
