import ToolkitControlCenter from "./ToolkitControlCenter";

export const dynamic = "force-dynamic";

export default function ToolkitPage() {
  return (
    <div className="min-h-screen bg-slate-50/60 p-4 sm:p-6">
      <ToolkitControlCenter />
    </div>
  );
}

