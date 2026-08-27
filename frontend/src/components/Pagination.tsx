import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}

export function Pagination({ page, pageSize, total, onPageChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;

  const candidates = [1, page - 1, page, page + 1, totalPages]
    .filter((value, index, values) => value >= 1 && value <= totalPages && values.indexOf(value) === index)
    .sort((left, right) => left - right);

  return (
    <nav className="pagination" aria-label="分页导航">
      <span>共 {total} 条</span>
      <div>
        <button className="icon-button" title="上一页" disabled={page <= 1} onClick={() => onPageChange(page - 1)}><ChevronLeft size={16} /></button>
        {candidates.map((value, index) => (
          <span key={value} className="page-number-wrap">
            {index > 0 && value - candidates[index - 1] > 1 && <i>...</i>}
            <button className={value === page ? "active" : ""} aria-current={value === page ? "page" : undefined} onClick={() => onPageChange(value)}>{value}</button>
          </span>
        ))}
        <button className="icon-button" title="下一页" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}><ChevronRight size={16} /></button>
      </div>
    </nav>
  );
}
