"use client";

import { useCallback, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";

interface UploadZoneProps {
  accept: string;
  multiple?: boolean;
  label: string;
  sublabel: string;
  onFilesSelected: (files: File[]) => void;
}

export function UploadZone({
  accept,
  multiple = false,
  label,
  sublabel,
  onFilesSelected,
}: UploadZoneProps) {
  const [isDragging, setIsDragging] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const files = Array.from(e.dataTransfer.files);
      onFilesSelected(files);
    },
    [onFilesSelected]
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files ? Array.from(e.target.files) : [];
      onFilesSelected(files);
    },
    [onFilesSelected]
  );

  return (
    <Card
      className={`border-2 border-dashed transition-colors cursor-pointer ${
        isDragging ? "border-primary bg-accent" : "border-border hover:border-primary/50"
      }`}
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
    >
      <CardContent className="flex flex-col items-center justify-center py-10 gap-2">
        <p className="text-lg font-medium">{label}</p>
        <p className="text-sm text-muted-foreground">{sublabel}</p>
        <label className="mt-3 px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm cursor-pointer hover:opacity-90">
          Browse files
          <input
            type="file"
            accept={accept}
            multiple={multiple}
            onChange={handleFileInput}
            className="hidden"
          />
        </label>
      </CardContent>
    </Card>
  );
}
