import { useOutletContext } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Upload } from "lucide-react";

import { errorMessage } from "../api/client.js";
import { datasets as datasetsApi } from "../api/endpoints.js";
import DatasetTable from "../features/datasets/DatasetTable.jsx";
import {
  Button, Card, CardBody, ErrorState, PageHeader, Skeleton,
} from "../components/ui/index.jsx";

export default function DatasetsPage() {
  const { onUploadClick } = useOutletContext() || {};
  const query = useQuery({ queryKey: ["datasets-status"], queryFn: datasetsApi.listWithStatus });

  return (
    <div>
      <PageHeader
        title="Datasets"
        description="Every dataset you've uploaded, with its cleaning and model status."
        actions={
          onUploadClick && <Button icon={Upload} onClick={onUploadClick}>Upload dataset</Button>
        }
      />

      <Card>
        <CardBody>
          {query.isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, index) => (
                <Skeleton key={index} className="h-12 w-full" />
              ))}
            </div>
          ) : query.isError ? (
            <ErrorState
              title="Could not load your datasets"
              message={errorMessage(query.error)}
              onRetry={query.refetch}
            />
          ) : (
            <DatasetTable datasets={query.data} onUploadClick={onUploadClick} />
          )}
        </CardBody>
      </Card>
    </div>
  );
}
